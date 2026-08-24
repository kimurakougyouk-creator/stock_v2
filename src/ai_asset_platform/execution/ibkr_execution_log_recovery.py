"""Recover one previously captured IBKR Paper execution from a durable text log.

Local-ledger recovery only. This module never creates, modifies, cancels, or
transmits a broker order. Recovery is deliberately narrow and fail-closed:
current broker Paper state must show exactly one SPY share, local confirmed
accounting must show zero SPY shares, and a prior execution-snapshot log must
contain exactly one valid SPY BUY whose price agrees with broker cost evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import order_manager
from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
)
from ai_asset_platform.execution.broker_position_guard import _local_confirmed_quantity
from ai_asset_platform.execution.ibkr_execution_reconcile import (
    ReconciliationResult,
    reconcile_execution_snapshot_to_ledger,
)

DEFAULT_EXECUTION_LOG = Path("results/ibkr_execution_snapshot_latest.log")

_EXECUTION_RE = re.compile(
    r"^EXECUTION\s+\d+:\s+"
    r"symbol=(?P<symbol>\S+)\s+"
    r"side=(?P<side>BUY|SELL)\s+"
    r"qty=(?P<qty>[0-9]+(?:\.[0-9]+)?)\s+"
    r"price=(?P<price>[0-9]+(?:\.[0-9]+)?)\s+"
    r"currency=(?P<currency>\S+)\s+"
    r"exchange=(?P<exchange>\S+)\s+"
    r"order_id=(?P<order_id>-?[0-9]+)\s+"
    r"perm_id=(?P<perm_id>-?[0-9]+)\s+"
    r"exec_id=(?P<exec_id>\S+)\s+"
    r"time=(?P<time>.+)$"
)


@dataclass(frozen=True)
class ExecutionLogRecoveryResult:
    recovered: bool
    reason: str
    reconciliation: ReconciliationResult | None = None


def _parse_execution_log(path: Path) -> tuple[IbkrExecutionEvidence, ...]:
    if not path.exists():
        return ()
    parsed: list[IbkrExecutionEvidence] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _EXECUTION_RE.match(raw.strip())
        if not match:
            continue
        values = match.groupdict()
        try:
            quantity = float(values["qty"])
            price = float(values["price"])
            order_id = int(values["order_id"])
            perm_id = int(values["perm_id"])
        except (TypeError, ValueError):
            continue
        exec_id = values["exec_id"].strip()
        currency = values["currency"].strip().upper()
        if quantity <= 0 or price <= 0 or not exec_id or exec_id == "UNKNOWN":
            continue
        if len(currency) != 3 or not currency.isalpha():
            continue
        parsed.append(
            IbkrExecutionEvidence(
                exec_id=exec_id,
                order_id=order_id,
                perm_id=perm_id,
                symbol=values["symbol"].strip().upper(),
                sec_type="STK",
                currency=currency,
                exchange=values["exchange"].strip().upper(),
                side=values["side"].strip().upper(),
                quantity=quantity,
                price=price,
                time=values["time"].strip(),
                account="",
            )
        )
    return tuple(parsed)


def _spy_broker_position(account: IbkrPaperAccountSnapshot):
    matches = [
        item
        for item in account.positions
        if item.symbol == "SPY" and item.sec_type in {"STK", "ETF"}
    ]
    return matches[0] if len(matches) == 1 else None


def _cost_matches_execution(*, execution_price: float, broker_average_cost: float, quantity: float) -> bool:
    """Accept only tiny, explainable broker-cost differences for the exact one-share fill.

    IBKR account snapshots may report stock average cost including small per-share
    commissions/fees while execDetails reports the pure execution price. For this
    recovery path we allow only a narrow absolute delta, and only for exactly one
    share, so we still fail closed on materially different broker cost evidence.
    """
    if quantity != 1.0 or execution_price <= 0 or broker_average_cost <= 0:
        return False
    delta = abs(float(execution_price) - float(broker_average_cost))
    return delta <= 1.00


def recover_spy_execution_from_log(
    *,
    execution_log_path: Path = DEFAULT_EXECUTION_LOG,
    order_log_path: Path = order_manager.ORDER_LOG_PATH,
    account: IbkrPaperAccountSnapshot | None = None,
) -> ExecutionLogRecoveryResult:
    broker = account if account is not None else preview_ibkr_paper_account_snapshot()
    if not broker.ready:
        return ExecutionLogRecoveryResult(False, "broker Paper account snapshot is not ready")

    position = _spy_broker_position(broker)
    if position is None or float(position.quantity) != 1.0:
        quantity = 0.0 if position is None else float(position.quantity)
        return ExecutionLogRecoveryResult(
            False, f"recovery requires exactly one broker-held SPY share; found {quantity:g}"
        )

    local_qty = _local_confirmed_quantity(order_manager.load_accounting_orders(), "SPY")
    if local_qty is None:
        return ExecutionLogRecoveryResult(False, "local SPY position cannot be reconstructed safely")
    if float(local_qty) == 1.0:
        return ExecutionLogRecoveryResult(False, "local SPY position is already reconciled")
    if float(local_qty) != 0.0:
        return ExecutionLogRecoveryResult(
            False, f"recovery requires local SPY quantity 0 before import; found {local_qty:g}"
        )

    candidates = [
        item
        for item in _parse_execution_log(execution_log_path)
        if item.symbol == "SPY"
        and item.side == "BUY"
        and item.quantity == 1.0
        and item.currency == "USD"
    ]
    if len(candidates) != 1:
        return ExecutionLogRecoveryResult(
            False, f"expected exactly one logged SPY BUY execution; found {len(candidates)}"
        )

    execution = candidates[0]
    broker_average_cost = float(position.average_cost)
    if broker_average_cost <= 0:
        return ExecutionLogRecoveryResult(False, "broker SPY average cost is unavailable")
    if not _cost_matches_execution(
        execution_price=float(execution.price),
        broker_average_cost=broker_average_cost,
        quantity=float(execution.quantity),
    ):
        return ExecutionLogRecoveryResult(
            False, "logged SPY BUY price does not match broker average cost closely enough"
        )

    snapshot = IbkrPaperExecutionSnapshot(
        connected=True,
        endpoint_port=broker.endpoint_port,
        executions=(execution,),
        order_sent=False,
        errors=(),
    )
    reconciliation = reconcile_execution_snapshot_to_ledger(
        snapshot, order_log_path=order_log_path
    )
    if reconciliation.errors or reconciliation.reconciled_count != 1:
        return ExecutionLogRecoveryResult(
            False, "logged execution could not be reconciled safely", reconciliation
        )
    return ExecutionLogRecoveryResult(
        True,
        "one prior broker-confirmed SPY BUY execution was recovered into the local ledger",
        reconciliation,
    )


def main() -> int:
    result = recover_spy_execution_from_log()
    print("===== IBKR PAPER EXECUTION LOG RECOVERY =====")
    print("RECOVERED       :", result.recovered)
    print("REASON          :", result.reason)
    print("REAL ORDER SENT : False")
    return 0 if result.recovered or "already reconciled" in result.reason else 2


if __name__ == "__main__":
    raise SystemExit(main())
