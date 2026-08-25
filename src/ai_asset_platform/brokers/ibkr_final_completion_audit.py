"""Final broker-read-only completion audit for the verified IBKR Paper baseline.

The audit never creates, changes, cancels, or transmits an order. The durable
legacy order ledger is stock/ETF-shaped, so derivative and pinned option E2E
executions are excluded from this aggregate stock accounting gate and are
verified by their dedicated multiplier-aware audits. The audit captures one
broker execution snapshot, reconciles it once, then reuses the same immutable
snapshot for the idempotency proof so an IBKR reqExecutions window change cannot
create a false failure.
"""
from __future__ import annotations

from dataclasses import dataclass

import order_manager
from config import TRADING_CAPITAL
from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    preview_ibkr_paper_execution_snapshot,
)
from ai_asset_platform.brokers.ibkr_operator_checkpoint import (
    _confirmed_held_quantity,
    _legacy_evidence_blockers,
    _trusted_accounting_records,
)
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.ibkr_execution_reconcile import (
    reconcile_execution_snapshot_to_ledger,
)
from ai_asset_platform.reports.multicurrency_confirmed_accounting import (
    MulticurrencyConfirmedAccountingError,
    MulticurrencyConfirmedAccountingSummary,
    audit_multicurrency_confirmed_accounting,
)
from ai_asset_platform.reports.multicurrency_trade_history import (
    MulticurrencyTradeHistoryError,
    RealizedTradeAccountCurrency,
    calculate_realized_trade_history,
)
from ai_asset_platform.reports.paired_spy_close_accounting import (
    PairedSpyCloseAccountingError,
    enrich_closed_spy_round_trip,
)

CONTROLLED_SYMBOLS = ("SPY", "AAPL", "9432")

# These executions are proven by dedicated derivative/option accounting audits
# and must never be flattened into the legacy stock/ETF ledger.
DEDICATED_AUDIT_EXEC_IDS = frozenset(
    {
        "0000e1a7.6a8f948c.01.01",  # ESU6 BUY
        "0000e1a7.6a8f948d.01.01",  # ESU6 SELL
        "00020057.6a8c86b2.01.01",  # pinned SPY option BUY
        "00020057.6a8c86b3.01.01",  # pinned SPY option SELL
    }
)


@dataclass(frozen=True)
class FinalCompletionAuditResult:
    passed: bool
    reasons: tuple[str, ...]
    first_reconciled_count: int
    second_reconciled_count: int
    broker_quantities: dict[str, float]
    local_quantities: dict[str, int | None]
    broker_position_count: int
    legacy_evidence_blockers: tuple[str, ...]
    accounting: MulticurrencyConfirmedAccountingSummary | None
    realized_trades: tuple[RealizedTradeAccountCurrency, ...]
    accounting_error: str | None = None
    trade_history_error: str | None = None
    real_order_sent: bool = False


def _broker_quantity(account: IbkrPaperAccountSnapshot, symbol: str) -> float:
    target = str(symbol).strip().upper()
    return sum(
        float(position.quantity)
        for position in account.positions
        if str(position.symbol).strip().upper() == target
    )


def _broker_exec_ids(record: dict) -> set[str]:
    return {
        str(value or "").strip()
        for value in list(record.get("broker_exec_ids") or [])
        if str(value or "").strip()
    }


def _belongs_to_dedicated_audit(record: dict) -> bool:
    return bool(_broker_exec_ids(record) & DEDICATED_AUDIT_EXEC_IDS)


def _aggregate_stock_records(records: list[dict]) -> list[dict]:
    """Return only records owned by the legacy stock/ETF accounting gate."""
    return [record for record in records if not _belongs_to_dedicated_audit(record)]


def _accounting_inputs() -> tuple[list[dict], tuple[str, ...]]:
    records = _aggregate_stock_records(list(order_manager.load_accounting_orders()))
    try:
        records = list(enrich_closed_spy_round_trip(records))
    except PairedSpyCloseAccountingError:
        # Do not manufacture SPY evidence. The later accounting/blocker checks
        # decide whether the observed durable evidence is safe enough to pass.
        pass
    account_currency = str(SETTINGS.account_currency).strip().upper()
    blockers = _legacy_evidence_blockers(records, account_currency=account_currency)
    trusted = _trusted_accounting_records(records, account_currency=account_currency)
    return trusted, blockers


def run_final_completion_audit() -> FinalCompletionAuditResult:
    reasons: list[str] = []

    snapshot = preview_ibkr_paper_execution_snapshot()
    first_reconcile = reconcile_execution_snapshot_to_ledger(
        snapshot,
        order_log_path=order_manager.ORDER_LOG_PATH,
    )
    if not snapshot.ready:
        reasons.append("broker execution snapshot is not ready")
    if first_reconcile.errors:
        reasons.append(f"first reconciliation errors: {list(first_reconcile.errors)}")

    account = preview_ibkr_paper_account_snapshot()
    if not account.ready:
        reasons.append("broker Paper account snapshot is not ready")
    if str(account.base_currency or "").strip().upper() != str(SETTINGS.account_currency).strip().upper():
        reasons.append("broker base currency does not match configured account currency")

    trusted_records, blockers = _accounting_inputs()
    if blockers:
        reasons.append(f"legacy evidence blockers remain: {list(blockers)}")

    local_quantities = {
        symbol: _confirmed_held_quantity(trusted_records, ticker=symbol)
        for symbol in CONTROLLED_SYMBOLS
    }
    broker_quantities = {
        symbol: _broker_quantity(account, symbol) if account.connected else float("nan")
        for symbol in CONTROLLED_SYMBOLS
    }
    for symbol in CONTROLLED_SYMBOLS:
        local = local_quantities[symbol]
        broker = broker_quantities[symbol]
        if local is None:
            reasons.append(f"local {symbol} quantity cannot be reconstructed safely")
        elif local != 0:
            reasons.append(f"local {symbol} quantity is not flat: {local}")
        if broker != broker:  # NaN
            reasons.append(f"broker {symbol} quantity is unavailable")
        elif abs(float(broker)) > 1e-9:
            reasons.append(f"broker {symbol} quantity is not flat: {broker:g}")

    accounting = None
    accounting_error = None
    try:
        accounting = audit_multicurrency_confirmed_accounting(
            trusted_records,
            initial_capital=float(TRADING_CAPITAL),
            account_currency=str(SETTINGS.account_currency).strip().upper(),
        )
    except MulticurrencyConfirmedAccountingError as exc:
        accounting_error = str(exc)
        reasons.append(f"trusted accounting failed: {exc}")

    realized_trades: tuple[RealizedTradeAccountCurrency, ...] = ()
    trade_history_error = None
    try:
        realized_trades = tuple(
            calculate_realized_trade_history(
                trusted_records,
                account_currency=str(SETTINGS.account_currency).strip().upper(),
            )
        )
    except MulticurrencyTradeHistoryError as exc:
        trade_history_error = str(exc)
        reasons.append(f"trusted trade history failed: {exc}")

    # Idempotency is a property of reconciling the same immutable broker
    # evidence twice. Do not make a second reqExecutions call: IBKR may return a
    # different history window even though durable state is already correct.
    second_reconcile = reconcile_execution_snapshot_to_ledger(
        snapshot,
        order_log_path=order_manager.ORDER_LOG_PATH,
    )
    if second_reconcile.errors:
        reasons.append(f"second reconciliation errors: {list(second_reconcile.errors)}")
    if second_reconcile.reconciled_count != 0:
        reasons.append(
            "second reconciliation of identical broker evidence changed durable state; idempotency proof failed"
        )

    return FinalCompletionAuditResult(
        passed=not reasons,
        reasons=tuple(reasons),
        first_reconciled_count=first_reconcile.reconciled_count,
        second_reconciled_count=second_reconcile.reconciled_count,
        broker_quantities=broker_quantities,
        local_quantities=local_quantities,
        broker_position_count=len(account.positions),
        legacy_evidence_blockers=blockers,
        accounting=accounting,
        realized_trades=realized_trades,
        accounting_error=accounting_error,
        trade_history_error=trade_history_error,
        real_order_sent=False,
    )


def main() -> int:
    result = run_final_completion_audit()
    accounting = result.accounting
    print("===== IBKR PAPER FINAL COMPLETION AUDIT =====")
    print("MODE                     : BROKER READ-ONLY / LOCAL RECONCILIATION ONLY")
    print("CONTROLLED SYMBOLS       :", ",".join(CONTROLLED_SYMBOLS))
    print("BROKER POSITION COUNT    :", result.broker_position_count)
    for symbol in CONTROLLED_SYMBOLS:
        print(f"BROKER {symbol} QTY          :", result.broker_quantities[symbol])
        print(f"LOCAL {symbol} QTY           :", result.local_quantities[symbol])
    print("FIRST RECONCILED COUNT   :", result.first_reconciled_count)
    print("SECOND RECONCILED COUNT  :", result.second_reconciled_count)
    print("LEGACY EVIDENCE BLOCKERS :", list(result.legacy_evidence_blockers))
    print("TRADE HISTORY COUNT      :", len(result.realized_trades))
    print("TRADE HISTORY ERROR      :", result.trade_history_error)
    print("ACCOUNTING ERROR         :", result.accounting_error)
    if accounting is not None:
        print("CONFIRMED FILLS          :", accounting.confirmed_fill_count)
        print("EQUITY POINTS            :", accounting.equity_point_count)
        print("ENDING CASH              :", accounting.ending_cash)
        print("ENDING HOLDINGS          :", accounting.ending_holdings)
        print("ENDING EQUITY            :", accounting.ending_equity)
        print("REALIZED PNL             :", accounting.realized_pnl)
        print("UNREALIZED PNL           :", accounting.unrealized_pnl)
        print("MAX DRAWDOWN             :", accounting.maximum_drawdown)
    print("AUDIT REASONS            :", list(result.reasons))
    print("FINAL COMPLETION GATE    :", "PASS" if result.passed else "BLOCKED")
    print("REAL ORDER SENT          : False")
    print("LIVE ORDER SENT          : False")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
