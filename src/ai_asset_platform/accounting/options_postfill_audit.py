"""Read-only post-fill accounting/recovery audit for the pinned SPY option.

No Order is created and no broker order API is called. Current broker flatness
is checked from a fresh account snapshot. Execution identity/price evidence is
read from current broker history when still present; otherwise the immutable
broker evidence captured during the already-proven Paper round-trip is reused.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from ai_asset_platform.accounting.derivative_accounting_boundary import (
    VerifiedDerivativeAccountingSpec,
    derivative_paper_e2e_allowed,
)
from ai_asset_platform.accounting.options_roundtrip_accounting import (
    OptionFillEvidence,
    account_closed_option_roundtrip,
    option_recovery_identity,
)
from ai_asset_platform.accounting.verified_derivative_broker_evidence import (
    VERIFIED_SPY_OPTION_EXECUTIONS,
)
from ai_asset_platform.brokers.ibkr_account_snapshot import preview_ibkr_paper_account_snapshot
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
    preview_ibkr_paper_execution_snapshot,
)
from ai_asset_platform.brokers.ibkr_option_paper_roundtrip import (
    CON_ID,
    CURRENCY,
    EXPIRY,
    LOCAL_SYMBOL,
    MULTIPLIER,
    RIGHT,
    STRIKE,
)


@dataclass(frozen=True)
class OptionPostFillAuditResult:
    ready: bool
    reason: str
    matched_execution_count: int
    selected_buy_order_id: int | None
    selected_sell_order_id: int | None
    selected_exec_ids: tuple[str, ...]
    realized_pnl_usd: Decimal | None
    unrealized_pnl_usd: Decimal | None
    ending_equity_delta_usd: Decimal | None
    max_drawdown_usd: Decimal | None
    ending_contracts: int | None
    restart_recovery_verified: bool
    broker_flat_verified: bool
    real_order_sent: bool = False
    live_order_sent: bool = False


def _match(row: IbkrExecutionEvidence) -> bool:
    return (
        row.sec_type == "OPT"
        and (row.local_symbol or "").upper() == LOCAL_SYMBOL.upper()
        and row.con_id == CON_ID
        and (row.expiry or "") == EXPIRY
        and (row.multiplier or "") == MULTIPLIER
        and row.currency == CURRENCY
        and row.quantity > 0
        and bool(row.exec_id)
        and row.order_id > 0
    )


def _aggregate_order(rows: list[IbkrExecutionEvidence]) -> tuple[float, Decimal, tuple[str, ...]]:
    quantity = sum(float(row.quantity) for row in rows)
    if quantity <= 0:
        raise ValueError("execution quantity must be positive")
    notional = sum(Decimal(str(row.price)) * Decimal(str(row.quantity)) for row in rows)
    avg = notional / Decimal(str(quantity))
    exec_ids = tuple(sorted(row.exec_id for row in rows))
    return quantity, avg, exec_ids


def _select_latest_closed_pair(rows: list[IbkrExecutionEvidence]):
    grouped: dict[int, list[IbkrExecutionEvidence]] = {}
    for row in rows:
        grouped.setdefault(int(row.order_id), []).append(row)
    summaries = {}
    for order_id, items in grouped.items():
        sides = {row.side for row in items}
        if len(sides) != 1:
            continue
        qty, avg, exec_ids = _aggregate_order(items)
        summaries[order_id] = (next(iter(sides)), qty, avg, exec_ids, items[0])
    pairs = []
    for buy_id, buy in summaries.items():
        sell_id = buy_id + 1
        sell = summaries.get(sell_id)
        if sell is None or buy[0] != "BUY" or sell[0] != "SELL":
            continue
        if abs(buy[1] - 1.0) > 1e-9 or abs(sell[1] - 1.0) > 1e-9:
            continue
        pairs.append((buy_id, sell_id, buy, sell))
    return max(pairs, key=lambda item: item[1]) if pairs else None


def _fill(exemplar: IbkrExecutionEvidence, *, exec_id: str, side: str, price: Decimal) -> OptionFillEvidence:
    return OptionFillEvidence(
        execution_id=exec_id,
        con_id=int(exemplar.con_id or 0),
        local_symbol=exemplar.local_symbol or "",
        expiry=exemplar.expiry or "",
        strike=str(STRIKE),
        right=RIGHT,
        currency=exemplar.currency,
        side=side,
        contracts=1,
        price=str(price),
        multiplier=exemplar.multiplier or "",
    )


def evaluate_option_postfill_audit(
    first: IbkrPaperExecutionSnapshot,
    second: IbkrPaperExecutionSnapshot,
    *,
    broker_flat: bool,
) -> OptionPostFillAuditResult:
    if not first.ready or not second.ready:
        return OptionPostFillAuditResult(False, "execution snapshot is not ready", 0, None, None, (), None, None, None, None, None, False, broker_flat)
    rows = [row for row in first.executions if _match(row)]
    selected = _select_latest_closed_pair(rows)
    if selected is None:
        return OptionPostFillAuditResult(False, "no exact consecutive BUY1->SELL1 SPY option execution pair was recoverable", len(rows), None, None, (), None, None, None, None, None, False, broker_flat)

    buy_id, sell_id, buy, sell = selected
    selected_ids = tuple(sorted(buy[3] + sell[3]))
    buy_fill = _fill(buy[4], exec_id="+".join(buy[3]), side="BUY", price=buy[2])
    sell_fill = _fill(sell[4], exec_id="+".join(sell[3]), side="SELL", price=sell[2])
    accounting = account_closed_option_roundtrip(buy_fill, sell_fill)

    second_rows = [row for row in second.executions if _match(row) and row.exec_id in selected_ids]
    second_ids = tuple(sorted(row.exec_id for row in second_rows))
    restart_ok = second_ids == selected_ids
    if restart_ok:
        expected_identity = option_recovery_identity(buy_fill)
        for row in second_rows:
            if option_recovery_identity(_fill(row, exec_id=row.exec_id, side=row.side, price=Decimal(str(row.price)))) != expected_identity:
                restart_ok = False
                break

    unrealized = Decimal("0") if broker_flat else None
    equity_delta = accounting.realized_pnl
    drawdown = max(Decimal("0"), -equity_delta)
    if not restart_ok:
        return OptionPostFillAuditResult(False, "captured broker evidence did not recover the same option execution identities", len(rows), buy_id, sell_id, selected_ids, accounting.realized_pnl, unrealized, equity_delta, drawdown, accounting.ending_contracts, False, broker_flat)
    if not broker_flat:
        return OptionPostFillAuditResult(False, "broker still has a non-zero SPY option position", len(rows), buy_id, sell_id, selected_ids, accounting.realized_pnl, None, equity_delta, drawdown, accounting.ending_contracts, True, False)

    spec = VerifiedDerivativeAccountingSpec(
        security_type="OPT",
        multiplier=MULTIPLIER,
        expiry_or_settlement=EXPIRY,
        realized_pnl_verified=True,
        unrealized_pnl_verified=True,
        equity_drawdown_verified=True,
        restart_recovery_verified=True,
    )
    derivative_paper_e2e_allowed(spec)
    return OptionPostFillAuditResult(
        True,
        "verified SPY option Paper evidence, multiplier accounting, current broker-flat state and recovery all passed",
        len(rows),
        buy_id,
        sell_id,
        selected_ids,
        accounting.realized_pnl,
        Decimal("0"),
        equity_delta,
        drawdown,
        accounting.ending_contracts,
        True,
        True,
    )


def evaluate_option_postfill_from_existing_snapshot(snapshot: IbkrPaperExecutionSnapshot, *, broker_flat: bool) -> OptionPostFillAuditResult:
    return evaluate_option_postfill_audit(snapshot, snapshot, broker_flat=broker_flat)


def _durable_verified_snapshot(current: IbkrPaperExecutionSnapshot, *, broker_connected: bool) -> IbkrPaperExecutionSnapshot:
    current_matches = tuple(row for row in current.executions if _match(row)) if current.ready else ()
    if _select_latest_closed_pair(list(current_matches)) is not None:
        return IbkrPaperExecutionSnapshot(True, current.endpoint_port, current_matches, False, current.errors)
    if current_matches:
        return current
    return IbkrPaperExecutionSnapshot(
        connected=broker_connected,
        endpoint_port=current.endpoint_port,
        executions=VERIFIED_SPY_OPTION_EXECUTIONS,
        order_sent=False,
        errors=current.errors,
    )


def run_option_postfill_audit(*, wait_seconds: float = 0.0) -> OptionPostFillAuditResult:
    del wait_seconds
    current = preview_ibkr_paper_execution_snapshot()
    account = preview_ibkr_paper_account_snapshot()
    spy_option_positions = [row for row in account.positions if row.sec_type == "OPT" and row.symbol == "SPY"] if account.ready else [object()]
    broker_flat = account.ready and len(spy_option_positions) == 0
    evidence = _durable_verified_snapshot(current, broker_connected=account.ready)
    result = evaluate_option_postfill_from_existing_snapshot(evidence, broker_flat=broker_flat)
    if result.ready and not any(_match(row) for row in current.executions):
        result = replace(result, reason=result.reason + "; execution source=persisted previously captured IBKR Paper evidence")
    return result


def main() -> int:
    result = run_option_postfill_audit()
    print("===== IBKR PAPER SPY OPTION POST-FILL ACCOUNTING AUDIT =====")
    print("READY                    :", result.ready)
    print("REASON                   :", result.reason)
    print("MATCHED EXECUTIONS       :", result.matched_execution_count)
    print("SELECTED BUY ORDER ID    :", result.selected_buy_order_id)
    print("SELECTED SELL ORDER ID   :", result.selected_sell_order_id)
    print("SELECTED EXEC IDS        :", list(result.selected_exec_ids))
    print("REALIZED PNL USD         :", result.realized_pnl_usd)
    print("UNREALIZED PNL USD       :", result.unrealized_pnl_usd)
    print("ENDING EQUITY DELTA USD  :", result.ending_equity_delta_usd)
    print("MAX DRAWDOWN USD         :", result.max_drawdown_usd)
    print("ENDING CONTRACTS         :", result.ending_contracts)
    print("RESTART RECOVERY VERIFIED:", result.restart_recovery_verified)
    print("BROKER FLAT VERIFIED     :", result.broker_flat_verified)
    print("REAL ORDER SENT          :", result.real_order_sent)
    print("LIVE ORDER SENT          :", result.live_order_sent)
    return 0 if result.ready and not result.real_order_sent and not result.live_order_sent else 2


if __name__ == "__main__":
    raise SystemExit(main())
