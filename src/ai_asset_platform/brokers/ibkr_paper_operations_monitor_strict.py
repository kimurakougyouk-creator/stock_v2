"""Strict unattended adapter for the IBKR Paper operations monitor.

This adapter fixes operational-scope hazards without weakening fail-closed
behavior:

* An unavailable broker account snapshot must not be misreported as a confirmed
  account-currency mismatch.
* Legacy local PAPER simulation rows must not be treated as current IBKR Paper
  positions. Accounting and active-risk checks here use only broker-confirmed
  ``IBKR_PAPER`` ``FILLED`` rows.
* Broker positions are verified by symbol, security type, currency, and total
  quantity so an option/derivative sharing an underlying symbol cannot masquerade
  as a verified stock/ETF position.

When the broker account snapshot is fully ready, every non-zero broker position
is checked against the exact verified Paper scope so a position created outside
this program cannot be silently ignored.

The adapter only uses read-only account, execution, and open-order snapshot
APIs. It never places, changes, cancels, closes, or retries an order. The
existing monitor continues to own persistence, notification, and CLI output.
"""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path

import order_manager

from ai_asset_platform.brokers import ibkr_paper_operations_monitor as base
from ai_asset_platform.brokers.ibkr_account_snapshot import (
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    preview_ibkr_paper_execution_snapshot,
)


_CURRENCY_MISMATCH_REASON = "broker and configured account currencies do not match"
_VERIFIED_BROKER_CONTRACTS = {
    "AAPL": ("AAPL", "STK", "USD"),
    "SPY": ("SPY", "STK", "USD"),
    "9432": ("9432.T", "STK", "JPY"),
}


def _ibkr_confirmed_records(records: list[dict]) -> list[dict]:
    """Return only broker-confirmed IBKR Paper fills for operational accounting."""
    return [
        record
        for record in records
        if isinstance(record, dict)
        and str(record.get("mode", "")).strip().upper() == "IBKR_PAPER"
        and str(record.get("status", "")).strip().upper() == "FILLED"
    ]


def _append_unique(items: list[str], message: str) -> None:
    normalized = str(message).strip()
    if normalized and normalized not in items:
        items.append(normalized)


def _combine_error(current: str | None, message: str) -> str:
    normalized = str(message).strip()
    if not current:
        return normalized
    return f"{current}; {normalized}"


def _broker_position_critical_reasons(account) -> tuple[str, ...]:
    """Check every complete-snapshot broker position against exact contracts."""
    if account is None or not bool(getattr(account, "ready", False)):
        return ()

    critical: list[str] = []
    totals: dict[str, float] = {}
    for position in tuple(getattr(account, "positions", ()) or ()):
        broker_symbol = str(getattr(position, "symbol", "") or "").strip().upper()
        sec_type = str(getattr(position, "sec_type", "") or "").strip().upper()
        currency = str(getattr(position, "currency", "") or "").strip().upper()
        try:
            quantity = float(getattr(position, "quantity"))
        except (TypeError, ValueError):
            quantity = float("nan")
        if not math.isfinite(quantity):
            _append_unique(
                critical,
                f"broker position quantity is invalid: {broker_symbol or 'UNKNOWN'}",
            )
            continue
        if quantity == 0:
            continue

        expected = _VERIFIED_BROKER_CONTRACTS.get(broker_symbol)
        if expected is None:
            _append_unique(
                critical,
                f"unverified broker position exists: {broker_symbol or 'UNKNOWN'}",
            )
            continue

        ticker, expected_sec_type, expected_currency = expected
        if sec_type != expected_sec_type or currency != expected_currency:
            _append_unique(
                critical,
                "unverified broker contract exists: "
                f"{broker_symbol} sec_type={sec_type or 'UNKNOWN'} "
                f"currency={currency or 'UNKNOWN'}",
            )
            continue
        totals[ticker] = totals.get(ticker, 0.0) + quantity

    for ticker, quantity in totals.items():
        verified_quantity = float(base.VERIFIED_SCOPE[ticker])
        if quantity != verified_quantity:
            _append_unique(
                critical,
                f"{ticker} broker held quantity {quantity:g} differs from verified quantity {verified_quantity:g}",
            )
    return tuple(critical)


def _finalize_strict_result(result: base.PaperOperationsMonitorResult, *, account):
    critical = list(result.critical_reasons)

    # A missing/unready snapshot has unknown currency, not a proven mismatch.
    if not result.account_ready:
        critical = [
            item for item in critical if item != _CURRENCY_MISMATCH_REASON
        ]

    for reason in _broker_position_critical_reasons(account):
        _append_unique(critical, reason)

    status = "CRITICAL" if critical else "WARNING" if result.warning_reasons else "HEALTHY"
    return replace(
        result,
        status=status,
        critical_reasons=tuple(critical),
    )


def run_strict_paper_operations_monitor_once(
    *,
    settings=base.SETTINGS,
    runtime_report_path: Path = base.DEFAULT_RUNTIME_REPORT_PATH,
    max_runtime_age_hours: float = base.DEFAULT_MAX_RUNTIME_AGE_HOURS,
) -> base.PaperOperationsMonitorResult:
    """Run one strict, read-only IBKR Paper monitoring cycle."""
    account = None
    execution_snapshot = None
    reconciliation = None
    reconciliation_error = None

    try:
        account = preview_ibkr_paper_account_snapshot()
    except Exception as exc:
        reconciliation_error = _combine_error(
            reconciliation_error,
            f"account snapshot unavailable: {exc}",
        )

    try:
        execution_snapshot = preview_ibkr_paper_execution_snapshot()
    except Exception as exc:
        reconciliation_error = _combine_error(
            reconciliation_error,
            f"execution snapshot unavailable: {exc}",
        )

    if account is not None and execution_snapshot is not None:
        try:
            reconciliation = base.audit_ibkr_reconciliation_evidence(
                account=account,
                execution_snapshot=execution_snapshot,
            )
        except Exception as exc:
            reconciliation_error = _combine_error(
                reconciliation_error,
                str(exc),
            )

    open_orders = None
    open_orders_error = None
    try:
        open_orders = base.preview_ibkr_paper_all_open_orders()
    except Exception as exc:
        open_orders_error = str(exc)

    accounting = None
    accounting_error = None
    ibkr_records: list[dict] | None = None
    try:
        accounting_records = order_manager.load_accounting_orders()
        ibkr_records = _ibkr_confirmed_records(accounting_records)
        accounting = base.audit_multicurrency_confirmed_accounting(
            ibkr_records,
            initial_capital=float(base.TRADING_CAPITAL),
            account_currency=str(settings.account_currency).strip().upper(),
        )
    except Exception as exc:
        accounting_error = str(exc)

    risk = None
    risk_error = None
    if ibkr_records is not None:
        try:
            risk = base.calculate_paper_risk_metrics(
                ibkr_records,
                settings=settings,
                now=base.account_now(),
            )
        except Exception as exc:
            risk_error = str(exc)
    else:
        risk_error = "IBKR Paper accounting records are unavailable"

    runtime_report, runtime_report_error = base.load_runtime_report(runtime_report_path)
    result = base.evaluate_paper_operations(
        settings=settings,
        reconciliation=reconciliation,
        reconciliation_error=reconciliation_error,
        open_orders=open_orders,
        open_orders_error=open_orders_error,
        accounting=accounting,
        accounting_error=accounting_error,
        risk=risk,
        risk_error=risk_error,
        runtime_report=runtime_report,
        runtime_report_error=runtime_report_error,
        now=base.account_now(),
        max_runtime_age_hours=max_runtime_age_hours,
    )
    return _finalize_strict_result(result, account=account)


def main() -> int:
    """Delegate output/persistence/email behavior to the proven base CLI."""
    original = base.run_paper_operations_monitor_once
    try:
        base.run_paper_operations_monitor_once = run_strict_paper_operations_monitor_once
        return base.main()
    finally:
        base.run_paper_operations_monitor_once = original


if __name__ == "__main__":
    raise SystemExit(main())
