"""Read-only IBKR Paper reconciliation evidence audit.

This module correlates the current broker Paper account snapshot, available
broker execution reports, and the durable local Paper ledger. It never creates,
changes, cancels, or transmits an order and it never mutates the local ledger.
Its purpose is to turn legacy AAPL/SPY discrepancies into one compact operator
report before any cleanup or recovery action is considered.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Iterable

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
    preview_ibkr_paper_execution_snapshot,
)
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.reports.paired_spy_close_accounting import (
    PairedSpyCloseAccountingError,
    enrich_closed_spy_round_trip,
)


@dataclass(frozen=True)
class LedgerBlockerEvidence:
    ticker: str
    order_intent_id: str
    reason: str
    side: str
    shares: int | None
    reference_price: float | None
    broker_order_id: int | None
    broker_exec_ids: tuple[str, ...]
    order_id_execution_matches: tuple[IbkrExecutionEvidence, ...]
    exec_id_execution_matches: tuple[IbkrExecutionEvidence, ...]
    symbol_execution_matches: tuple[IbkrExecutionEvidence, ...]


@dataclass(frozen=True)
class SymbolReconciliationEvidence:
    ticker: str
    broker_quantity: float
    broker_average_cost: float | None
    broker_market_price: float | None
    local_confirmed_quantity: int | None
    quantity_gap: float | None
    available_execution_count: int


@dataclass(frozen=True)
class IbkrReconciliationEvidenceAudit:
    account_ready: bool
    execution_snapshot_ready: bool
    endpoint_port: int | None
    account_currency: str | None
    blockers: tuple[LedgerBlockerEvidence, ...]
    symbols: tuple[SymbolReconciliationEvidence, ...]
    next_action: str
    order_sent: bool = False
    ledger_changed: bool = False


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = raw.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _normalized_exec_ids(record: dict) -> tuple[str, ...]:
    values = record.get("broker_exec_ids")
    if not isinstance(values, (list, tuple)):
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def _missing_evidence_reason(record: dict, *, account_currency: str) -> str | None:
    if str(record.get("mode", "")).strip().upper() != "IBKR_PAPER":
        return None
    if str(record.get("status", "")).strip().upper() != "FILLED":
        return None
    currency = str(record.get("currency", "")).strip().upper()
    if not currency:
        return "missing-currency"
    if len(currency) != 3 or not currency.isalpha():
        return "invalid-currency"
    if currency == account_currency:
        return None
    try:
        fx = float(record.get("fx_to_account_rate"))
    except (TypeError, ValueError):
        fx = 0.0
    if fx <= 0:
        return "missing-historical-fx"
    return None


def _whole_shares(record: dict) -> int | None:
    try:
        value = float(record.get("shares"))
    except (TypeError, ValueError):
        return None
    if value <= 0 or not value.is_integer():
        return None
    return int(value)


def _price(record: dict) -> float | None:
    try:
        value = float(record.get("reference_price"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _broker_order_id(record: dict) -> int | None:
    raw = record.get("broker_order_id")
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _confirmed_quantity(records: Iterable[dict], ticker: str) -> int | None:
    target = str(ticker).strip().upper()
    held = 0
    seen_intents: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("mode", "")).strip().upper() != "IBKR_PAPER":
            continue
        if str(record.get("status", "")).strip().upper() != "FILLED":
            continue
        if str(record.get("ticker", "")).strip().upper() != target:
            continue
        intent = str(record.get("order_intent_id", "")).strip()
        if intent and intent in seen_intents:
            continue
        shares = _whole_shares(record)
        side = str(record.get("side", "")).strip().upper()
        if shares is None or side not in {"BUY", "SELL"}:
            return None
        if side == "BUY":
            held += shares
        else:
            if shares > held:
                return None
            held -= shares
        if intent:
            seen_intents.add(intent)
    return held


def _broker_position(account: IbkrPaperAccountSnapshot, ticker: str):
    target = str(ticker).strip().upper()
    matches = [item for item in account.positions if str(item.symbol).strip().upper() == target]
    if not matches:
        return None
    if len(matches) != 1:
        return None
    return matches[0]


def _execution_matches(
    record: dict,
    executions: tuple[IbkrExecutionEvidence, ...],
) -> tuple[tuple[IbkrExecutionEvidence, ...], tuple[IbkrExecutionEvidence, ...], tuple[IbkrExecutionEvidence, ...]]:
    ticker = str(record.get("ticker", "")).strip().upper()
    broker_order_id = _broker_order_id(record)
    exec_ids = set(_normalized_exec_ids(record))
    by_order = tuple(
        item for item in executions
        if broker_order_id is not None and int(item.order_id) == broker_order_id
    )
    by_exec = tuple(item for item in executions if str(item.exec_id).strip() in exec_ids)
    by_symbol = tuple(item for item in executions if str(item.symbol).strip().upper() == ticker)
    return by_order, by_exec, by_symbol


def _blockers(
    records: list[dict],
    *,
    account_currency: str,
    executions: tuple[IbkrExecutionEvidence, ...],
) -> tuple[LedgerBlockerEvidence, ...]:
    result: list[LedgerBlockerEvidence] = []
    for index, record in enumerate(records, start=1):
        reason = _missing_evidence_reason(record, account_currency=account_currency)
        if reason is None:
            continue
        by_order, by_exec, by_symbol = _execution_matches(record, executions)
        result.append(
            LedgerBlockerEvidence(
                ticker=str(record.get("ticker", "")).strip().upper() or "UNKNOWN",
                order_intent_id=str(record.get("order_intent_id", "")).strip() or f"row-{index}",
                reason=reason,
                side=str(record.get("side", "")).strip().upper(),
                shares=_whole_shares(record),
                reference_price=_price(record),
                broker_order_id=_broker_order_id(record),
                broker_exec_ids=_normalized_exec_ids(record),
                order_id_execution_matches=by_order,
                exec_id_execution_matches=by_exec,
                symbol_execution_matches=by_symbol,
            )
        )
    return tuple(result)


def _symbol_evidence(
    ticker: str,
    *,
    records: list[dict],
    account: IbkrPaperAccountSnapshot,
    executions: tuple[IbkrExecutionEvidence, ...],
) -> SymbolReconciliationEvidence:
    local = _confirmed_quantity(records, ticker)
    position = _broker_position(account, ticker)
    broker_qty = 0.0 if position is None else float(position.quantity)
    avg_cost = None if position is None or float(position.average_cost) <= 0 else float(position.average_cost)
    market_price = None if position is None or float(position.market_price) <= 0 else float(position.market_price)
    gap = None if local is None else broker_qty - float(local)
    available = sum(1 for item in executions if str(item.symbol).strip().upper() == ticker)
    return SymbolReconciliationEvidence(
        ticker=ticker,
        broker_quantity=broker_qty,
        broker_average_cost=avg_cost,
        broker_market_price=market_price,
        local_confirmed_quantity=local,
        quantity_gap=gap,
        available_execution_count=available,
    )


def _next_action(
    *,
    account: IbkrPaperAccountSnapshot,
    execution_snapshot: IbkrPaperExecutionSnapshot,
    blockers: tuple[LedgerBlockerEvidence, ...],
    symbols: tuple[SymbolReconciliationEvidence, ...],
) -> str:
    if not account.ready:
        return "BLOCKED_BROKER_ACCOUNT_SNAPSHOT_NOT_READY"
    if not execution_snapshot.ready:
        return "BLOCKED_EXECUTION_SNAPSHOT_NOT_READY"
    by_symbol = {item.ticker: item for item in symbols}
    aapl = by_symbol.get("AAPL")
    if aapl is not None and aapl.quantity_gap not in (None, 0.0):
        return "REVIEW_AAPL_PAPER_POSITION_RESET_BEFORE_NEW_EXPOSURE"
    for blocker in blockers:
        if len(blocker.order_id_execution_matches) == 1 or len(blocker.exec_id_execution_matches) == 1:
            return "RECOVER_UNIQUE_BROKER_EXECUTION_EVIDENCE"
    if blockers:
        return "LEGACY_EVIDENCE_REMAINS_UNRECOVERABLE"
    return "RECONCILIATION_EVIDENCE_IS_CLEAN"


def audit_ibkr_reconciliation_evidence(
    *,
    order_log_path: Path = Path("results/paper_orders.jsonl"),
    account: IbkrPaperAccountSnapshot | None = None,
    execution_snapshot: IbkrPaperExecutionSnapshot | None = None,
) -> IbkrReconciliationEvidenceAudit:
    records = _load_jsonl(order_log_path)
    evidence_records = records
    try:
        evidence_records = enrich_closed_spy_round_trip(records)
    except PairedSpyCloseAccountingError:
        # Keep the original row incomplete when broker execution identity is
        # ambiguous.  The audit must fail closed instead of manufacturing FX.
        evidence_records = records
    broker_account = account or preview_ibkr_paper_account_snapshot()
    broker_executions = execution_snapshot or preview_ibkr_paper_execution_snapshot()
    account_currency = str(broker_account.base_currency or SETTINGS.account_currency).strip().upper()
    blockers = _blockers(
        evidence_records,
        account_currency=account_currency,
        executions=tuple(broker_executions.executions),
    )
    symbols = tuple(
        _symbol_evidence(
            ticker,
            records=evidence_records,
            account=broker_account,
            executions=tuple(broker_executions.executions),
        )
        for ticker in ("AAPL", "SPY")
    )
    return IbkrReconciliationEvidenceAudit(
        account_ready=broker_account.ready,
        execution_snapshot_ready=broker_executions.ready,
        endpoint_port=broker_account.endpoint_port or broker_executions.endpoint_port,
        account_currency=broker_account.base_currency,
        blockers=blockers,
        symbols=symbols,
        next_action=_next_action(
            account=broker_account,
            execution_snapshot=broker_executions,
            blockers=blockers,
            symbols=symbols,
        ),
        order_sent=bool(broker_account.order_sent or broker_executions.order_sent),
        ledger_changed=False,
    )


def _execution_line(item: IbkrExecutionEvidence) -> str:
    return (
        f"symbol={item.symbol} side={item.side} qty={item.quantity:g} price={item.price:g} "
        f"currency={item.currency or 'UNKNOWN'} order_id={item.order_id} "
        f"perm_id={item.perm_id} exec_id={item.exec_id or 'UNKNOWN'} time={item.time or 'UNKNOWN'}"
    )


def main() -> int:
    result = audit_ibkr_reconciliation_evidence()
    print("===== IBKR PAPER RECONCILIATION EVIDENCE AUDIT =====")
    print("ACCOUNT READY          :", result.account_ready)
    print("EXECUTION SNAPSHOT READY:", result.execution_snapshot_ready)
    print("ENDPOINT PORT          :", result.endpoint_port)
    print("ACCOUNT CURRENCY       :", result.account_currency)
    print("LEDGER CHANGED         :", result.ledger_changed)
    print("ORDER SENT             :", result.order_sent)
    print("NEXT ACTION            :", result.next_action)
    for item in result.symbols:
        print(
            f"SYMBOL {item.ticker}: broker_qty={item.broker_quantity:g} "
            f"local_qty={item.local_confirmed_quantity} gap={item.quantity_gap} "
            f"avg_cost={item.broker_average_cost} market_price={item.broker_market_price} "
            f"available_execs={item.available_execution_count}"
        )
    print("BLOCKER COUNT          :", len(result.blockers))
    for index, blocker in enumerate(result.blockers, start=1):
        print(
            f"BLOCKER {index}: ticker={blocker.ticker} intent={blocker.order_intent_id} "
            f"reason={blocker.reason} side={blocker.side} shares={blocker.shares} "
            f"price={blocker.reference_price} broker_order_id={blocker.broker_order_id} "
            f"broker_exec_ids={list(blocker.broker_exec_ids)}"
        )
        print("  ORDER-ID MATCHES     :", len(blocker.order_id_execution_matches))
        for execution in blocker.order_id_execution_matches:
            print("   ", _execution_line(execution))
        print("  EXEC-ID MATCHES      :", len(blocker.exec_id_execution_matches))
        for execution in blocker.exec_id_execution_matches:
            print("   ", _execution_line(execution))
        print("  SYMBOL EXECUTIONS    :", len(blocker.symbol_execution_matches))
        for execution in blocker.symbol_execution_matches:
            print("   ", _execution_line(execution))
    print("REAL LIVE ORDER SENT   : False")
    return 0 if result.account_ready and result.execution_snapshot_ready and not result.order_sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
