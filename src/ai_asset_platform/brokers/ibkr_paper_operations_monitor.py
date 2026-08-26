"""Comprehensive, read-only health monitor for verified IBKR Paper operation.

The monitor observes broker/account reconciliation, every open order, trusted
local accounting, and the most recent deliberate verified-runtime report.  It
never places, changes, cancels, closes, or retries an order.  Problems are
recorded for manual review and the monitor continues on later cycles.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import order_manager
from config import TRADING_CAPITAL

from ai_asset_platform.brokers.ibkr_all_open_orders_snapshot import (
    IbkrAllOpenOrdersSnapshot,
    preview_ibkr_paper_all_open_orders,
)
from ai_asset_platform.brokers.ibkr_reconciliation_evidence_audit import (
    IbkrReconciliationEvidenceAudit,
    audit_ibkr_reconciliation_evidence,
)
from ai_asset_platform.core.account_clock import account_now
from ai_asset_platform.core.settings import SETTINGS, PlatformSettings
from ai_asset_platform.execution.ibkr_verified_paper_runtime import (
    DEFAULT_RUNTIME_REPORT_PATH,
    RUNTIME_REPORT_SCHEMA_VERSION,
    VERIFIED_SCOPE,
)
from ai_asset_platform.execution.account_calendar_ledger import (
    AccountCalendarLedgerError,
    position_holding_days,
    record_time_in_account_zone,
)
from ai_asset_platform.reports.multicurrency_confirmed_accounting import (
    MulticurrencyConfirmedAccountingError,
    MulticurrencyConfirmedAccountingSummary,
    audit_multicurrency_confirmed_accounting,
)
from ai_asset_platform.reports.multicurrency_trade_history import (
    MulticurrencyTradeHistoryError,
    calculate_realized_trade_history,
)


DEFAULT_MONITOR_LATEST_PATH = Path(
    "results/ibkr_paper_operations_monitor_latest.json"
)
DEFAULT_MONITOR_HISTORY_PATH = Path(
    "results/ibkr_paper_operations_monitor_history.jsonl"
)
DEFAULT_MONITOR_STATUS_PATH = Path(
    "results/ibkr_paper_operations_monitor_status.txt"
)
DEFAULT_MONITOR_NOTIFICATION_STATE_PATH = Path(
    "results/ibkr_paper_operations_monitor_notification_state.json"
)
DEFAULT_MAX_RUNTIME_AGE_HOURS = 96.0
DEFAULT_MAX_HISTORY_BYTES = 10 * 1024 * 1024
_VALID_ENDPOINT_PORTS = {4002, 7497}


@dataclass(frozen=True)
class PaperOperationsMonitorResult:
    status: str
    checked_at: str
    critical_reasons: tuple[str, ...]
    warning_reasons: tuple[str, ...]
    account_ready: bool
    execution_snapshot_ready: bool
    endpoint_port: int | None
    account_currency: str | None
    reconciliation_next_action: str | None
    reconciliation_blocker_count: int
    symbols: tuple[dict, ...]
    open_orders_ready: bool
    open_order_count: int
    open_orders: tuple[dict, ...]
    accounting_safe: bool
    accounting: dict | None
    risk_safe: bool
    risk: dict | None
    runtime_report_present: bool
    runtime_status: str | None
    runtime_age_hours: float | None
    runtime: dict | None
    notification_status: str = "NOT_EVALUATED"
    order_sent: bool = False
    live_order_sent: bool = False

    def as_record(self) -> dict:
        return {
            "schema_version": 1,
            "status": self.status,
            "checked_at": self.checked_at,
            "critical_reasons": list(self.critical_reasons),
            "warning_reasons": list(self.warning_reasons),
            "broker": {
                "account_ready": self.account_ready,
                "execution_snapshot_ready": self.execution_snapshot_ready,
                "endpoint_port": self.endpoint_port,
                "account_currency": self.account_currency,
                "reconciliation_next_action": self.reconciliation_next_action,
                "reconciliation_blocker_count": self.reconciliation_blocker_count,
                "symbols": list(self.symbols),
                "all_open_orders_ready": self.open_orders_ready,
                "open_order_count": self.open_order_count,
                "open_orders": list(self.open_orders),
            },
            "accounting": self.accounting,
            "accounting_safe": self.accounting_safe,
            "risk": self.risk,
            "risk_safe": self.risk_safe,
            "runtime_report_present": self.runtime_report_present,
            "runtime_status": self.runtime_status,
            "runtime_age_hours": self.runtime_age_hours,
            "runtime": self.runtime,
            "notification_status": self.notification_status,
            "monitor_order_sent": self.order_sent,
            "live_order_sent": self.live_order_sent,
        }


def _append_unique(items: list[str], message: str) -> None:
    normalized = str(message).strip()
    if normalized and normalized not in items:
        items.append(normalized)


def _parse_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _runtime_age_hours(
    report: dict | None, *, now: datetime
) -> float | None:
    if not report:
        return None
    completed = _parse_timestamp(report.get("completed_at"))
    if completed is None:
        return None
    return (now - completed.astimezone(now.tzinfo)).total_seconds() / 3600.0


def _symbol_records(
    reconciliation: IbkrReconciliationEvidenceAudit | None,
) -> tuple[dict, ...]:
    if reconciliation is None:
        return ()
    return tuple(
        {
            "ticker": item.ticker,
            "broker_quantity": item.broker_quantity,
            "local_confirmed_quantity": item.local_confirmed_quantity,
            "quantity_gap": item.quantity_gap,
            "broker_average_cost": item.broker_average_cost,
            "broker_market_price": item.broker_market_price,
            "available_execution_count": item.available_execution_count,
        }
        for item in reconciliation.symbols
    )


def _open_order_records(
    snapshot: IbkrAllOpenOrdersSnapshot | None,
) -> tuple[dict, ...]:
    if snapshot is None:
        return ()
    return tuple(
        {
            "order_id": item.order_id,
            "symbol": item.symbol,
            "local_symbol": item.local_symbol,
            "sec_type": item.sec_type,
            "currency": item.currency,
            "exchange": item.exchange,
            "action": item.action,
            "quantity": item.quantity,
            "order_type": item.order_type,
            "status": item.status,
            "client_id": item.client_id,
            "perm_id": item.perm_id,
        }
        for item in snapshot.orders
    )


def _accounting_record(
    summary: MulticurrencyConfirmedAccountingSummary | None,
) -> dict | None:
    if summary is None:
        return None
    return {
        "account_currency": summary.account_currency,
        "confirmed_fill_count": summary.confirmed_fill_count,
        "equity_point_count": summary.equity_point_count,
        "ending_cash": summary.ending_cash,
        "ending_holdings": summary.ending_holdings,
        "ending_equity": summary.ending_equity,
        "realized_pnl": summary.realized_pnl,
        "unrealized_pnl": summary.unrealized_pnl,
        "maximum_drawdown": summary.maximum_drawdown,
    }


class PaperOperationsRiskError(ValueError):
    """Raised when active risk state cannot be reconstructed safely."""


def _deduped_records(records: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen_intents: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise PaperOperationsRiskError("accounting record must be an object")
        intent = str(record.get("order_intent_id", "")).strip()
        if intent and intent in seen_intents:
            continue
        result.append(record)
        if intent:
            seen_intents.add(intent)
    return result


def _positive_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperOperationsRiskError(f"{field} must be numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise PaperOperationsRiskError(f"{field} must be positive")
    return parsed


def _account_value(record: dict, *, account_currency: str) -> Decimal:
    try:
        shares = int(record.get("shares"))
    except (TypeError, ValueError) as exc:
        raise PaperOperationsRiskError("accounting shares must be whole") from exc
    if shares <= 0:
        raise PaperOperationsRiskError("accounting shares must be positive")
    price = _positive_decimal(record.get("reference_price"), field="reference_price")
    currency = str(record.get("currency", "") or "").strip().upper()
    if not currency:
        if str(record.get("mode", "")).strip().upper() == "IBKR_PAPER":
            raise PaperOperationsRiskError("IBKR Paper fill is missing currency")
        currency = account_currency
    if len(currency) != 3 or not currency.isalpha():
        raise PaperOperationsRiskError("fill currency is invalid")
    raw_fx = record.get("fx_to_account_rate")
    if currency == account_currency:
        fx = Decimal("1") if raw_fx in (None, "") else _positive_decimal(
            raw_fx, field="fx_to_account_rate"
        )
        if fx != Decimal("1"):
            raise PaperOperationsRiskError(
                "same-currency fill requires fx_to_account_rate=1 or omission"
            )
    else:
        if raw_fx in (None, ""):
            raise PaperOperationsRiskError(
                f"{currency} fill is missing account-currency FX evidence"
            )
        fx = _positive_decimal(raw_fx, field="fx_to_account_rate")
    return Decimal(shares) * price * fx


def calculate_paper_risk_metrics(
    records: list[dict],
    *,
    settings: PlatformSettings,
    now: datetime,
) -> dict:
    """Calculate active risk counters from deduplicated confirmed evidence."""
    materialized = _deduped_records(records)
    account_currency = str(settings.account_currency).strip().upper()
    positions: dict[str, int] = {}
    daily_buy_count = 0
    daily_sell_count = 0
    daily_trading_amount = Decimal("0")
    try:
        account_zone = ZoneInfo(str(settings.account_timezone).strip())
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise PaperOperationsRiskError("account_timezone is invalid") from exc
    current_date = now.astimezone(account_zone).date()
    try:
        for record in materialized:
            ticker = str(record.get("ticker", "")).strip().upper()
            side = str(record.get("side", "")).strip().upper()
            if not ticker or side not in {"BUY", "SELL"}:
                raise PaperOperationsRiskError("accounting ticker/side is invalid")
            try:
                shares = int(record.get("shares"))
            except (TypeError, ValueError) as exc:
                raise PaperOperationsRiskError("accounting shares must be whole") from exc
            if shares <= 0:
                raise PaperOperationsRiskError("accounting shares must be positive")
            held = positions.get(ticker, 0)
            if side == "BUY":
                positions[ticker] = held + shares
            else:
                if shares > held:
                    raise PaperOperationsRiskError(
                        f"confirmed SELL for {ticker} exceeds holdings"
                    )
                positions[ticker] = held - shares

            recorded = record_time_in_account_zone(record, settings)
            if recorded.date() == current_date:
                if side == "BUY":
                    daily_buy_count += 1
                else:
                    daily_sell_count += 1
                daily_trading_amount += _account_value(
                    record, account_currency=account_currency
                )
    except AccountCalendarLedgerError as exc:
        raise PaperOperationsRiskError(str(exc)) from exc

    active_positions = {
        ticker: quantity for ticker, quantity in positions.items() if quantity > 0
    }
    holding_days: dict[str, int] = {}
    for ticker in active_positions:
        try:
            days = position_holding_days(
                materialized,
                ticker=ticker,
                settings=settings,
                now=now,
            )
        except AccountCalendarLedgerError as exc:
            raise PaperOperationsRiskError(str(exc)) from exc
        if days is None:
            raise PaperOperationsRiskError(
                f"holding age for {ticker} cannot be reconstructed"
            )
        holding_days[ticker] = days

    try:
        trades = calculate_realized_trade_history(
            materialized, account_currency=account_currency
        )
    except MulticurrencyTradeHistoryError as exc:
        raise PaperOperationsRiskError(str(exc)) from exc
    daily_realized = Decimal("0")
    for trade in trades:
        if not trade.sold_at:
            raise PaperOperationsRiskError("realized trade is missing sold_at")
        try:
            sold = record_time_in_account_zone(
                {"created_at": trade.sold_at}, settings
            )
        except AccountCalendarLedgerError as exc:
            raise PaperOperationsRiskError(str(exc)) from exc
        if sold.date() == current_date:
            daily_realized += Decimal(str(trade.realized_pnl_account))
    consecutive_losses = 0
    for trade in reversed(trades):
        if trade.realized_pnl_account < 0:
            consecutive_losses += 1
        else:
            break

    return {
        "account_date": current_date.isoformat(),
        "positions": active_positions,
        "position_count": len(active_positions),
        "holding_days": holding_days,
        "daily_buy_count": daily_buy_count,
        "daily_sell_count": daily_sell_count,
        "daily_trading_amount_account": float(daily_trading_amount),
        "daily_realized_pnl_account": float(daily_realized),
        "consecutive_losses": consecutive_losses,
        "limits": {
            "max_positions": int(getattr(settings, "max_positions", 0)),
            "max_daily_buy_orders": int(
                getattr(settings, "max_daily_buy_orders", 0)
            ),
            "max_daily_sell_orders": int(
                getattr(settings, "max_daily_sell_orders", 0)
            ),
            "max_daily_trading_amount_account": float(
                getattr(settings, "max_daily_trading_amount_yen", 0.0)
            ),
            "daily_loss_limit_account": float(
                getattr(settings, "daily_loss_limit_yen", 0.0)
            ),
            "max_consecutive_losses": int(
                getattr(settings, "max_consecutive_losses", 0)
            ),
            "max_holding_days": int(getattr(settings, "max_holding_days", 0)),
        },
    }


def evaluate_paper_operations(
    *,
    settings: PlatformSettings,
    reconciliation: IbkrReconciliationEvidenceAudit | None,
    reconciliation_error: str | None,
    open_orders: IbkrAllOpenOrdersSnapshot | None,
    open_orders_error: str | None,
    accounting: MulticurrencyConfirmedAccountingSummary | None,
    accounting_error: str | None,
    risk: dict | None,
    risk_error: str | None,
    runtime_report: dict | None,
    runtime_report_error: str | None,
    now: datetime,
    max_runtime_age_hours: float = DEFAULT_MAX_RUNTIME_AGE_HOURS,
) -> PaperOperationsMonitorResult:
    if now.tzinfo is None:
        raise ValueError("monitor time must be timezone-aware")
    if not math.isfinite(float(max_runtime_age_hours)) or max_runtime_age_hours <= 0:
        raise ValueError("max_runtime_age_hours must be positive")

    critical: list[str] = []
    warnings: list[str] = []

    if not settings.enable_paper_trading:
        _append_unique(critical, "Paper Trading is disabled")
    if settings.enable_live_trading or settings.live_trading_unlocked:
        _append_unique(critical, "Live Trading safety lock is not intact")

    if reconciliation_error:
        _append_unique(warnings, f"reconciliation audit unavailable: {reconciliation_error}")
    if reconciliation is None:
        _append_unique(warnings, "reconciliation audit did not return a snapshot")
    else:
        if reconciliation.order_sent:
            _append_unique(critical, "read-only reconciliation unexpectedly reported an order")
        if reconciliation.ledger_changed:
            _append_unique(critical, "read-only reconciliation unexpectedly changed the ledger")
        if not reconciliation.account_ready:
            _append_unique(warnings, "broker Paper account snapshot is not ready")
        if not reconciliation.execution_snapshot_ready:
            _append_unique(warnings, "broker execution snapshot is not ready")
        if reconciliation.endpoint_port not in _VALID_ENDPOINT_PORTS:
            _append_unique(warnings, "verified IBKR Paper endpoint is unavailable")
        if str(reconciliation.account_currency or "").strip().upper() != str(
            settings.account_currency
        ).strip().upper():
            _append_unique(critical, "broker and configured account currencies do not match")
        if reconciliation.blockers:
            _append_unique(
                critical,
                f"reconciliation has {len(reconciliation.blockers)} evidence blocker(s)",
            )
        action = str(reconciliation.next_action or "").strip()
        if action != "RECONCILIATION_EVIDENCE_IS_CLEAN":
            if action.startswith("BLOCKED_BROKER_") or action.startswith(
                "BLOCKED_EXECUTION_"
            ):
                _append_unique(warnings, f"reconciliation not ready: {action}")
            else:
                _append_unique(critical, f"reconciliation is not clean: {action}")

        symbols = {item.ticker: item for item in reconciliation.symbols}
        expected_tickers = set(VERIFIED_SCOPE)
        if set(symbols) != expected_tickers:
            _append_unique(critical, "reconciliation does not cover the exact verified scope")
        for ticker in sorted(expected_tickers):
            item = symbols.get(ticker)
            if item is None:
                continue
            if item.local_confirmed_quantity is None or item.quantity_gap is None:
                _append_unique(critical, f"{ticker} local quantity cannot be reconstructed")
            elif float(item.quantity_gap) != 0.0:
                _append_unique(
                    critical,
                    f"{ticker} broker/local quantity gap is {item.quantity_gap:g}",
                )

    if open_orders_error:
        _append_unique(warnings, f"all-open-orders snapshot unavailable: {open_orders_error}")
    if open_orders is None:
        _append_unique(warnings, "all-open-orders audit did not return a snapshot")
    else:
        if open_orders.order_sent:
            _append_unique(critical, "open-order audit unexpectedly reported an order")
        if not open_orders.ready:
            _append_unique(warnings, "all-open-orders snapshot is not ready")
        if open_orders.orders:
            _append_unique(
                critical,
                f"broker reports {len(open_orders.orders)} open order(s); manual review required",
            )

    if accounting_error:
        _append_unique(critical, f"trusted accounting is unsafe: {accounting_error}")
    if accounting is None:
        _append_unique(critical, "trusted accounting summary is unavailable")
    else:
        if str(accounting.account_currency).strip().upper() != str(
            settings.account_currency
        ).strip().upper():
            _append_unique(critical, "accounting currency does not match configuration")
        values = (
            accounting.ending_cash,
            accounting.ending_holdings,
            accounting.ending_equity,
            accounting.realized_pnl,
            accounting.unrealized_pnl,
            accounting.maximum_drawdown,
        )
        if not all(math.isfinite(float(value)) for value in values):
            _append_unique(critical, "accounting contains a non-finite value")
        if accounting.ending_equity <= 0:
            _append_unique(critical, "accounting ending equity is not positive")
        if accounting.maximum_drawdown < 0:
            _append_unique(critical, "accounting maximum drawdown is invalid")

    if risk_error:
        _append_unique(critical, f"active risk state is unsafe: {risk_error}")
    if risk is None:
        _append_unique(critical, "active risk metrics are unavailable")
    else:
        positions = dict(risk.get("positions") or {})
        for ticker, quantity in positions.items():
            verified_quantity = VERIFIED_SCOPE.get(ticker)
            if verified_quantity is None:
                _append_unique(critical, f"unverified open position exists: {ticker}")
            elif int(quantity) != int(verified_quantity):
                _append_unique(
                    critical,
                    f"{ticker} held quantity {quantity} differs from verified quantity {verified_quantity}",
                )
        limits = dict(risk.get("limits") or {})
        max_positions = int(limits.get("max_positions") or 0)
        if max_positions > 0 and int(risk.get("position_count") or 0) > max_positions:
            _append_unique(critical, "maximum position count is exceeded")
        max_buys = int(limits.get("max_daily_buy_orders") or 0)
        if max_buys > 0 and int(risk.get("daily_buy_count") or 0) > max_buys:
            _append_unique(critical, "daily BUY order limit is exceeded")
        max_sells = int(limits.get("max_daily_sell_orders") or 0)
        if max_sells > 0 and int(risk.get("daily_sell_count") or 0) > max_sells:
            _append_unique(critical, "daily SELL order limit is exceeded")
        max_amount = float(limits.get("max_daily_trading_amount_account") or 0.0)
        if max_amount > 0 and float(
            risk.get("daily_trading_amount_account") or 0.0
        ) > max_amount:
            _append_unique(critical, "daily trading amount limit is exceeded")
        loss_limit = float(limits.get("daily_loss_limit_account") or 0.0)
        if loss_limit > 0 and float(
            risk.get("daily_realized_pnl_account") or 0.0
        ) <= -loss_limit:
            _append_unique(critical, "daily realized loss limit is reached")
        max_losses = int(limits.get("max_consecutive_losses") or 0)
        if max_losses > 0 and int(risk.get("consecutive_losses") or 0) >= max_losses:
            _append_unique(critical, "maximum consecutive losses is reached")
        max_holding_days = int(limits.get("max_holding_days") or 0)
        if max_holding_days > 0:
            overdue = {
                ticker: int(days)
                for ticker, days in dict(risk.get("holding_days") or {}).items()
                if int(days) >= max_holding_days
            }
            if overdue:
                _append_unique(
                    warnings,
                    f"position holding-time exit is due: {overdue}",
                )

    age_hours = _runtime_age_hours(runtime_report, now=now)
    if runtime_report_error:
        _append_unique(critical, f"runtime report is invalid: {runtime_report_error}")
    if runtime_report is None:
        _append_unique(
            warnings,
            "no structured verified-runtime report exists yet; broker monitoring remains active",
        )
    else:
        if runtime_report.get("schema_version") != RUNTIME_REPORT_SCHEMA_VERSION:
            _append_unique(critical, "runtime report schema version is unsupported")
        if runtime_report.get("live_order_sent") is not False:
            _append_unique(critical, "runtime report does not prove Live order sent is false")
        if runtime_report.get("live_trading") != "PROHIBITED":
            _append_unique(critical, "runtime report does not preserve the Live prohibition")
        if runtime_report.get("scope") != VERIFIED_SCOPE:
            _append_unique(critical, "runtime report scope differs from the verified scope")
        runtime_status = str(runtime_report.get("status", "")).strip().upper()
        if runtime_status != "SUCCESS":
            _append_unique(critical, f"latest verified runtime status is {runtime_status or 'UNKNOWN'}")
        try:
            analysis_count = int(runtime_report.get("analysis_record_count"))
            error_count = int(runtime_report.get("error_count"))
            execution_error_count = int(runtime_report.get("execution_error_count"))
        except (TypeError, ValueError):
            _append_unique(critical, "runtime report counters are invalid")
        else:
            if analysis_count != len(VERIFIED_SCOPE):
                _append_unique(critical, "latest runtime did not analyze the complete verified scope")
            if error_count != 0 or execution_error_count != 0:
                _append_unique(
                    critical,
                    "latest runtime contains analysis or execution errors",
                )
        decisions = runtime_report.get("final_decisions")
        if not isinstance(decisions, list):
            _append_unique(critical, "runtime final decisions are unavailable")
        else:
            tickers = {
                str(item.get("ticker", "")).strip().upper()
                for item in decisions
                if isinstance(item, dict)
            }
            if tickers != set(VERIFIED_SCOPE):
                _append_unique(critical, "runtime final decisions do not cover the verified scope")
            for item in decisions:
                if not isinstance(item, dict) or str(
                    item.get("final_signal", "")
                ).strip().upper() not in {"BUY", "SELL", "HOLD"}:
                    _append_unique(critical, "runtime contains an invalid final signal")
                    break
        if age_hours is None:
            _append_unique(critical, "runtime completion timestamp is invalid")
        elif age_hours < -(5.0 / 60.0):
            _append_unique(critical, "runtime completion timestamp is in the future")
        elif age_hours > float(max_runtime_age_hours):
            _append_unique(
                warnings,
                f"latest verified runtime is stale ({age_hours:.1f} hours old)",
            )

    status = "CRITICAL" if critical else "WARNING" if warnings else "HEALTHY"
    runtime_status = (
        str(runtime_report.get("status", "")).strip().upper()
        if runtime_report is not None
        else None
    )
    return PaperOperationsMonitorResult(
        status=status,
        checked_at=now.isoformat(timespec="seconds"),
        critical_reasons=tuple(critical),
        warning_reasons=tuple(warnings),
        account_ready=bool(reconciliation and reconciliation.account_ready),
        execution_snapshot_ready=bool(
            reconciliation and reconciliation.execution_snapshot_ready
        ),
        endpoint_port=reconciliation.endpoint_port if reconciliation else None,
        account_currency=reconciliation.account_currency if reconciliation else None,
        reconciliation_next_action=(
            reconciliation.next_action if reconciliation else None
        ),
        reconciliation_blocker_count=(
            len(reconciliation.blockers) if reconciliation else 0
        ),
        symbols=_symbol_records(reconciliation),
        open_orders_ready=bool(open_orders and open_orders.ready),
        open_order_count=len(open_orders.orders) if open_orders else 0,
        open_orders=_open_order_records(open_orders),
        accounting_safe=accounting is not None and accounting_error is None,
        accounting=_accounting_record(accounting),
        risk_safe=risk is not None and risk_error is None,
        risk=risk,
        runtime_report_present=runtime_report is not None,
        runtime_status=runtime_status,
        runtime_age_hours=age_hours,
        runtime=runtime_report,
        notification_status="NOT_EVALUATED",
        order_sent=bool(
            (reconciliation and reconciliation.order_sent)
            or (open_orders and open_orders.order_sent)
        ),
        live_order_sent=False,
    )


def load_runtime_report(
    path: Path = DEFAULT_RUNTIME_REPORT_PATH,
) -> tuple[dict | None, str | None]:
    if not path.exists():
        return None, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "runtime report must be a JSON object"
    return value, None


def _rotate_history(path: Path, *, max_history_bytes: int) -> None:
    if not path.exists():
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < max_history_bytes:
        return
    rotated = path.with_suffix(path.suffix + ".1")
    path.replace(rotated)


def _write_notification_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def maybe_send_monitor_email_alert(
    result: PaperOperationsMonitorResult,
    *,
    sender: str,
    app_password: str,
    now: datetime,
    state_path: Path = DEFAULT_MONITOR_NOTIFICATION_STATE_PATH,
    cooldown_hours: float = 12.0,
    send_mail_fn=None,
) -> str:
    """Send only status transitions or bounded repeat alerts to the owner."""
    if now.tzinfo is None:
        raise ValueError("notification time must be timezone-aware")
    if not math.isfinite(float(cooldown_hours)) or cooldown_hours <= 0:
        raise ValueError("cooldown_hours must be positive")
    if not str(sender).strip() or not str(app_password):
        return "NOT_CONFIGURED"

    previous: dict = {}
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, json.JSONDecodeError):
            previous = {}
    prior_status = str(previous.get("status", "")).strip().upper()
    prior_sent = _parse_timestamp(previous.get("last_sent_at"))
    prior_attempt = _parse_timestamp(previous.get("last_attempt_at"))
    reference_time = prior_sent
    if prior_attempt is not None and (
        reference_time is None or prior_attempt > reference_time
    ):
        reference_time = prior_attempt
    elapsed_hours = (
        (now - reference_time.astimezone(now.tzinfo)).total_seconds() / 3600.0
        if reference_time is not None
        else None
    )

    if not prior_status and result.status == "HEALTHY":
        _write_notification_state(
            state_path,
            {
                "status": result.status,
                "last_sent_at": None,
                "last_attempt_at": None,
                "last_error": None,
                "updated_at": now.isoformat(timespec="seconds"),
            },
        )
        return "BASELINE_RECORDED"

    should_send = prior_status != result.status
    if (
        not should_send
        and result.status in {"WARNING", "CRITICAL"}
        and (elapsed_hours is None or elapsed_hours >= cooldown_hours)
    ):
        should_send = True
    if not should_send:
        _write_notification_state(
            state_path,
            {
                "status": result.status,
                "last_sent_at": previous.get("last_sent_at"),
                "last_attempt_at": previous.get("last_attempt_at"),
                "last_error": previous.get("last_error"),
                "updated_at": now.isoformat(timespec="seconds"),
            },
        )
        return "UNCHANGED_SUPPRESSED"

    if send_mail_fn is None:
        from mail import send_mail as send_mail_fn

    reasons = list(result.critical_reasons) + list(result.warning_reasons)
    body_lines = [
        f"IBKR Paper operations monitor status: {result.status}",
        f"Checked at: {result.checked_at}",
        f"Open orders: {result.open_order_count}",
        f"Accounting safe: {result.accounting_safe}",
        f"Risk safe: {result.risk_safe}",
        f"Runtime status: {result.runtime_status}",
        "",
        "Reasons:",
        *([f"- {item}" for item in reasons] or ["- status recovered to HEALTHY"]),
        "",
        "No order was changed, cancelled, closed, or retried by the monitor.",
        "Live Trading remains prohibited.",
    ]
    try:
        send_mail_fn(
            sender,
            app_password,
            sender,
            f"[IBKR Paper Monitor] {result.status}",
            "\n".join(body_lines),
        )
    except Exception as exc:
        _write_notification_state(
            state_path,
            {
                "status": result.status,
                "last_sent_at": previous.get("last_sent_at"),
                "last_attempt_at": now.isoformat(timespec="seconds"),
                "last_error": str(exc),
                "updated_at": now.isoformat(timespec="seconds"),
            },
        )
        return f"ERROR: {exc}"
    _write_notification_state(
        state_path,
        {
            "status": result.status,
            "last_sent_at": now.isoformat(timespec="seconds"),
            "last_attempt_at": now.isoformat(timespec="seconds"),
            "last_error": None,
            "updated_at": now.isoformat(timespec="seconds"),
        },
    )
    return "SENT"


def persist_monitor_result(
    result: PaperOperationsMonitorResult,
    *,
    latest_path: Path = DEFAULT_MONITOR_LATEST_PATH,
    history_path: Path = DEFAULT_MONITOR_HISTORY_PATH,
    status_path: Path = DEFAULT_MONITOR_STATUS_PATH,
    max_history_bytes: int = DEFAULT_MAX_HISTORY_BYTES,
) -> None:
    if max_history_bytes <= 0:
        raise ValueError("max_history_bytes must be positive")
    for path in (latest_path, history_path, status_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    record = result.as_record()
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
    latest_temporary = latest_path.with_suffix(latest_path.suffix + ".tmp")
    latest_temporary.write_text(serialized + "\n", encoding="utf-8")
    latest_temporary.replace(latest_path)
    _rotate_history(history_path, max_history_bytes=max_history_bytes)
    with history_path.open("a", encoding="utf-8") as history:
        history.write(serialized + "\n")
    status_lines = [
        f"STATUS: {result.status}",
        f"CHECKED_AT: {result.checked_at}",
        f"CRITICAL_COUNT: {len(result.critical_reasons)}",
        *[f"CRITICAL: {item}" for item in result.critical_reasons],
        f"WARNING_COUNT: {len(result.warning_reasons)}",
        *[f"WARNING: {item}" for item in result.warning_reasons],
        f"OPEN_ORDER_COUNT: {result.open_order_count}",
        f"ACCOUNTING_SAFE: {result.accounting_safe}",
        f"RISK_SAFE: {result.risk_safe}",
        f"NOTIFICATION_STATUS: {result.notification_status}",
        "MONITOR_ORDER_SENT: False",
        "LIVE_ORDER_SENT: False",
    ]
    status_temporary = status_path.with_suffix(status_path.suffix + ".tmp")
    status_temporary.write_text("\n".join(status_lines) + "\n", encoding="utf-8")
    status_temporary.replace(status_path)


def run_paper_operations_monitor_once(
    *,
    settings: PlatformSettings = SETTINGS,
    runtime_report_path: Path = DEFAULT_RUNTIME_REPORT_PATH,
    max_runtime_age_hours: float = DEFAULT_MAX_RUNTIME_AGE_HOURS,
) -> PaperOperationsMonitorResult:
    reconciliation = None
    reconciliation_error = None
    try:
        reconciliation = audit_ibkr_reconciliation_evidence()
    except Exception as exc:
        reconciliation_error = str(exc)

    open_orders = None
    open_orders_error = None
    try:
        open_orders = preview_ibkr_paper_all_open_orders()
    except Exception as exc:
        open_orders_error = str(exc)

    accounting = None
    accounting_error = None
    accounting_records: list[dict] | None = None
    try:
        accounting_records = order_manager.load_accounting_orders()
        accounting = audit_multicurrency_confirmed_accounting(
            accounting_records,
            initial_capital=float(TRADING_CAPITAL),
            account_currency=str(settings.account_currency).strip().upper(),
        )
    except (OSError, json.JSONDecodeError, MulticurrencyConfirmedAccountingError) as exc:
        accounting_error = str(exc)
    except Exception as exc:
        accounting_error = f"unexpected accounting error: {exc}"

    risk = None
    risk_error = None
    if accounting_records is not None:
        try:
            risk = calculate_paper_risk_metrics(
                accounting_records,
                settings=settings,
                now=account_now(),
            )
        except PaperOperationsRiskError as exc:
            risk_error = str(exc)
        except Exception as exc:
            risk_error = f"unexpected risk error: {exc}"
    else:
        risk_error = "accounting records are unavailable"

    runtime_report, runtime_report_error = load_runtime_report(runtime_report_path)
    return evaluate_paper_operations(
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
        now=account_now(),
        max_runtime_age_hours=max_runtime_age_hours,
    )


def _bounded_environment_number(
    name: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ValueError(f"{name} must be from {minimum:g} to {maximum:g}")
    return value


def main() -> int:
    print("===== IBKR PAPER OPERATIONS MONITOR =====")
    print("MODE                  : READ ONLY")
    print("AUTO CANCEL/RETRY     : PROHIBITED")
    print("LIVE TRADING          : PROHIBITED")
    try:
        max_age = _bounded_environment_number(
            "IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS",
            default=DEFAULT_MAX_RUNTIME_AGE_HOURS,
            minimum=1.0,
            maximum=720.0,
        )
        max_history = int(
            _bounded_environment_number(
                "IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES",
                default=float(DEFAULT_MAX_HISTORY_BYTES),
                minimum=float(1024 * 1024),
                maximum=float(100 * 1024 * 1024),
            )
        )
        notification_cooldown = _bounded_environment_number(
            "IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS",
            default=12.0,
            minimum=1.0,
            maximum=168.0,
        )
    except ValueError as exc:
        print("STATUS                : CRITICAL")
        print("REASON                :", str(exc))
        print("MONITOR ORDER SENT    : False")
        print("LIVE ORDER SENT       : False")
        return 2

    result = run_paper_operations_monitor_once(max_runtime_age_hours=max_age)
    notification_mode = os.getenv(
        "IBKR_PAPER_MONITOR_EMAIL_ALERTS", "auto"
    ).strip().lower()
    if notification_mode not in {"auto", "1", "true", "yes", "on", "0", "false", "no", "off"}:
        notification_status = "ERROR: IBKR_PAPER_MONITOR_EMAIL_ALERTS is invalid"
    elif notification_mode in {"0", "false", "no", "off"}:
        notification_status = "DISABLED"
    else:
        from config import APP_PASSWORD, EMAIL_ADDRESS

        try:
            notification_status = maybe_send_monitor_email_alert(
                result,
                sender=EMAIL_ADDRESS,
                app_password=APP_PASSWORD,
                now=account_now(),
                cooldown_hours=notification_cooldown,
            )
        except Exception as exc:
            notification_status = f"ERROR: {exc}"
    if notification_status == "NOT_CONFIGURED" or notification_status.startswith("ERROR:"):
        message = (
            "email alert delivery is not configured"
            if notification_status == "NOT_CONFIGURED"
            else f"email alert delivery failed: {notification_status[6:].strip()}"
        )
        warnings = list(result.warning_reasons)
        _append_unique(warnings, message)
        result = replace(
            result,
            status="CRITICAL" if result.critical_reasons else "WARNING",
            warning_reasons=tuple(warnings),
            notification_status=notification_status,
        )
    else:
        result = replace(result, notification_status=notification_status)
    try:
        persist_monitor_result(result, max_history_bytes=max_history)
    except Exception as exc:
        print("STATUS                : CRITICAL")
        print("REASON                : monitoring evidence could not be persisted:", str(exc))
        print("MONITOR ORDER SENT    : False")
        print("LIVE ORDER SENT       : False")
        return 2

    print("STATUS                :", result.status)
    print("CHECKED AT            :", result.checked_at)
    print("ACCOUNT READY         :", result.account_ready)
    print("EXECUTION READY       :", result.execution_snapshot_ready)
    print("ENDPOINT PORT         :", result.endpoint_port)
    print("RECONCILIATION        :", result.reconciliation_next_action)
    print("BLOCKER COUNT         :", result.reconciliation_blocker_count)
    for item in result.symbols:
        print(
            f"SYMBOL {item['ticker']}: broker={item['broker_quantity']:g} "
            f"local={item['local_confirmed_quantity']} gap={item['quantity_gap']}"
        )
    print("OPEN ORDERS READY     :", result.open_orders_ready)
    print("OPEN ORDER COUNT      :", result.open_order_count)
    print("ACCOUNTING SAFE       :", result.accounting_safe)
    print("RISK SAFE             :", result.risk_safe)
    if result.risk is not None:
        print("POSITION COUNT        :", result.risk["position_count"])
        print("DAILY BUY/SELL COUNT  :", f"{result.risk['daily_buy_count']}/{result.risk['daily_sell_count']}")
        print("DAILY TRADING AMOUNT  :", result.risk["daily_trading_amount_account"])
        print("DAILY REALIZED PNL    :", result.risk["daily_realized_pnl_account"])
    print("CONSECUTIVE LOSSES    :", result.risk["consecutive_losses"])
    print("EMAIL ALERT STATUS    :", result.notification_status)
    print("RUNTIME REPORT        :", result.runtime_report_present)
    print("RUNTIME STATUS        :", result.runtime_status)
    print("RUNTIME AGE HOURS     :", result.runtime_age_hours)
    print("CRITICAL COUNT        :", len(result.critical_reasons))
    for item in result.critical_reasons:
        print("CRITICAL              :", item)
    print("WARNING COUNT         :", len(result.warning_reasons))
    for item in result.warning_reasons:
        print("WARNING               :", item)
    print("LATEST JSON           :", DEFAULT_MONITOR_LATEST_PATH)
    print("HISTORY JSONL         :", DEFAULT_MONITOR_HISTORY_PATH)
    print("STATUS FILE           :", DEFAULT_MONITOR_STATUS_PATH)
    print("MONITOR ORDER SENT    :", result.order_sent)
    print("LIVE ORDER SENT       :", result.live_order_sent)
    return 0 if result.status == "HEALTHY" else 1 if result.status == "WARNING" else 2


if __name__ == "__main__":
    raise SystemExit(main())
