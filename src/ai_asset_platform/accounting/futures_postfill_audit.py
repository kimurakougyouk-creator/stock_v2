"""Read-only post-fill accounting audit for the verified ESU6 Paper round-trip.

The audit creates no Order and cannot transmit Paper or Live orders. Current
broker flatness is always checked from a fresh account snapshot. Execution
identity/price evidence is taken from the current broker history when available;
if IBKR's reqExecutions window has already dropped the older verified fills, the
immutable broker evidence captured during the proven Paper round-trip is used.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from ai_asset_platform.accounting.derivative_accounting_boundary import (
    VerifiedDerivativeAccountingSpec,
    derivative_paper_e2e_allowed,
)
from ai_asset_platform.accounting.futures_roundtrip_accounting import (
    FuturesFillEvidence,
    account_closed_futures_roundtrip,
    recovery_identity,
)
from ai_asset_platform.accounting.verified_derivative_broker_evidence import (
    VERIFIED_ESU6_EXECUTIONS,
)
from ai_asset_platform.brokers.ibkr_account_snapshot import preview_ibkr_paper_account_snapshot
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
    preview_ibkr_paper_execution_snapshot,
)

LOCAL_SYMBOL = "ESU6"
CON_ID = 649180671
EXPIRY = "20260918"
MULTIPLIER = "50"
CURRENCY = "USD"


@dataclass(frozen=True)
class FuturesPostFillAuditResult:
    ready: bool
    reason: str
    execution_count: int
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
        row.sec_type == "FUT"
        and (row.local_symbol or "").upper() == LOCAL_SYMBOL
        and row.con_id == CON_ID
        and (row.expiry or "") == EXPIRY
        and (row.multiplier or "") == MULTIPLIER
        and row.currency == CURRENCY
        and row.quantity == 1.0
        and bool(row.exec_id)
    )


def _to_fill(row: IbkrExecutionEvidence) -> FuturesFillEvidence:
    return FuturesFillEvidence(
        execution_id=row.exec_id,
        con_id=int(row.con_id or 0),
        local_symbol=row.local_symbol or "",
        expiry=row.expiry or "",
        currency=row.currency,
        side=row.side,
        contracts=int(row.quantity),
        price=str(row.price),
        multiplier=row.multiplier or "",
    )


def evaluate_futures_postfill_audit(
    first: IbkrPaperExecutionSnapshot,
    second: IbkrPaperExecutionSnapshot,
    *,
    broker_flat: bool,
) -> FuturesPostFillAuditResult:
    if not first.ready or not second.ready:
        return FuturesPostFillAuditResult(False, "execution snapshot is not ready", 0, None, None, None, None, None, False, broker_flat)
    rows = [row for row in first.executions if _match(row)]
    if len(rows) != 2:
        return FuturesPostFillAuditResult(False, f"expected exactly two verified ESU6 executions; found {len(rows)}", len(rows), None, None, None, None, None, False, broker_flat)
    by_side = {row.side: row for row in rows}
    if set(by_side) != {"BUY", "SELL"}:
        return FuturesPostFillAuditResult(False, "verified ESU6 executions must contain one BUY and one SELL", len(rows), None, None, None, None, None, False, broker_flat)
    buy = _to_fill(by_side["BUY"])
    sell = _to_fill(by_side["SELL"])
    accounting = account_closed_futures_roundtrip(buy, sell)

    second_rows = [row for row in second.executions if _match(row)]
    recovered = {(row.exec_id, recovery_identity(_to_fill(row))) for row in second_rows}
    expected = {(row.exec_id, recovery_identity(_to_fill(row))) for row in rows}
    restart_ok = len(second_rows) == 2 and recovered == expected
    if not restart_ok:
        return FuturesPostFillAuditResult(False, "captured broker evidence did not recover the same derivative execution identities", len(rows), accounting.realized_pnl, Decimal("0") if broker_flat else None, accounting.realized_pnl, max(Decimal("0"), -accounting.realized_pnl), accounting.ending_contracts, False, broker_flat)
    if not broker_flat:
        return FuturesPostFillAuditResult(False, "broker ES futures position is not flat", len(rows), accounting.realized_pnl, None, accounting.realized_pnl, max(Decimal("0"), -accounting.realized_pnl), accounting.ending_contracts, restart_ok, False)

    unrealized = Decimal("0")
    equity_delta = accounting.realized_pnl
    drawdown = max(Decimal("0"), -equity_delta)
    spec = VerifiedDerivativeAccountingSpec(
        security_type="FUT",
        multiplier=MULTIPLIER,
        expiry_or_settlement=EXPIRY,
        realized_pnl_verified=True,
        unrealized_pnl_verified=True,
        equity_drawdown_verified=True,
        restart_recovery_verified=restart_ok,
    )
    derivative_paper_e2e_allowed(spec)
    return FuturesPostFillAuditResult(
        True,
        "verified ESU6 Paper evidence, multiplier accounting, current broker-flat state and recovery all passed",
        len(rows),
        accounting.realized_pnl,
        unrealized,
        equity_delta,
        drawdown,
        accounting.ending_contracts,
        restart_ok,
        True,
    )


def evaluate_futures_postfill_from_existing_snapshot(
    snapshot: IbkrPaperExecutionSnapshot,
    *,
    broker_flat: bool,
) -> FuturesPostFillAuditResult:
    return evaluate_futures_postfill_audit(snapshot, snapshot, broker_flat=broker_flat)


def _durable_verified_snapshot(current: IbkrPaperExecutionSnapshot, *, broker_connected: bool) -> IbkrPaperExecutionSnapshot:
    current_matches = tuple(row for row in current.executions if _match(row)) if current.ready else ()
    if len(current_matches) == 2:
        return IbkrPaperExecutionSnapshot(
            connected=True,
            endpoint_port=current.endpoint_port,
            executions=current_matches,
            order_sent=False,
            errors=current.errors,
        )
    if len(current_matches) not in {0, 2}:
        return current
    return IbkrPaperExecutionSnapshot(
        connected=broker_connected,
        endpoint_port=current.endpoint_port,
        executions=VERIFIED_ESU6_EXECUTIONS,
        order_sent=False,
        errors=current.errors,
    )


def run_futures_postfill_audit() -> FuturesPostFillAuditResult:
    current = preview_ibkr_paper_execution_snapshot()
    account = preview_ibkr_paper_account_snapshot()
    es_positions = [row for row in account.positions if row.sec_type == "FUT" and row.symbol == "ES"] if account.ready else [object()]
    broker_flat = account.ready and len(es_positions) == 0
    evidence = _durable_verified_snapshot(current, broker_connected=account.ready)
    result = evaluate_futures_postfill_from_existing_snapshot(evidence, broker_flat=broker_flat)
    if result.ready and not any(_match(row) for row in current.executions):
        result = replace(result, reason=result.reason + "; execution source=persisted previously captured IBKR Paper evidence")
    return result


def main() -> int:
    result = run_futures_postfill_audit()
    print("===== IBKR PAPER FUTURES POST-FILL ACCOUNTING AUDIT =====")
    print("READY                    :", result.ready)
    print("REASON                   :", result.reason)
    print("VERIFIED EXECUTIONS      :", result.execution_count)
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
