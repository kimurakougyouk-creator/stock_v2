"""Final same-run evidence binding for one operational Live pilot.

This gate is intentionally stricter than the broader readiness report. It is
meant to be evaluated immediately before the operator-authorization/send phase
so evidence from different Live endpoints, accounts, or widely separated
snapshots cannot be mixed together.

For the first cash pilot it also requires settled cash in the instrument currency
plus an explicit conservative reserve, so margin buying power or an implicit FX
conversion cannot silently substitute for prepared cash.

The module is read-only: it opens no broker connection and contains no order API.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from pathlib import Path

from ai_asset_platform.core.settings import SETTINGS, PlatformSettings
from ai_asset_platform.execution.live_pilot_emergency_stop import (
    DEFAULT_STOP_PATH,
    live_pilot_stop_is_active,
)


DEFAULT_MAX_AGE_SECONDS = 30.0
DEFAULT_MAX_SKEW_SECONDS = 15.0
_VALID_LIVE_ENDPOINT_PORTS = {4001, 7496}
_VALID_PAPER_ENDPOINT_PORTS = {4002, 7497}
_USD_TICKERS = {"AAPL", "SPY"}
_INSTRUMENT_CURRENCY = {"AAPL": "USD", "SPY": "USD", "9432.T": "JPY"}
_SETTLED_CASH_RESERVE = {"JPY": 1_000.0, "USD": 10.0}
_BASE_AVAILABLE_FUNDS_RESERVE_JPY = 1_000.0


@dataclass(frozen=True)
class LivePilotSameRunPreflight:
    status: str
    checked_at: str
    blockers: tuple[str, ...]
    ticker: str
    account_fingerprint: str
    account_fingerprint_match: bool
    endpoint_port: int | None
    endpoint_binding_ready: bool
    evidence_fresh: bool
    evidence_skew_seconds: float | None
    operational_readiness_ready: bool
    paper_monitor_safe: bool
    emergency_stop_clear: bool
    live_global_lock_intact: bool
    ready: bool
    available_funds_jpy: float | None = None
    required_available_funds_jpy: float | None = None
    available_funds_ready: bool = False
    settled_cash_currency: str | None = None
    settled_cash_amount: float | None = None
    required_settled_cash_amount: float | None = None
    settled_cash_ready: bool = False
    broker_connection_used: bool = False
    order_sent: bool = False
    live_order_sent: bool = False


def _now_utc(value: datetime | None) -> datetime:
    current = value if value is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("same-run preflight clock must be timezone-aware")
    return current.astimezone(timezone.utc)


def _timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive(value: object) -> float | None:
    parsed = _finite(value)
    return parsed if parsed is not None and parsed > 0 else None


def _port(report: dict | None) -> int | None:
    if not isinstance(report, dict):
        return None
    try:
        value = int(report.get("endpoint_port"))
    except (TypeError, ValueError):
        return None
    return value if value in _VALID_LIVE_ENDPOINT_PORTS else None


def _read_only_clean(report: dict | None) -> bool:
    if not isinstance(report, dict):
        return False
    if report.get("ready") is not True or report.get("connection_mode") != "LIVE_READ_ONLY":
        return False
    if report.get("order_sent") is not False or report.get("live_order_sent") is not False:
        return False
    if "cancel_sent" in report and report.get("cancel_sent") is not False:
        return False
    return True


def _paper_safe(report: dict | None) -> bool:
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        return False
    broker = report.get("broker")
    if not isinstance(broker, dict):
        return False
    blocker_count = broker.get("reconciliation_blocker_count")
    open_order_count = broker.get("open_order_count")
    open_orders = broker.get("open_orders")
    endpoint_port = broker.get("endpoint_port")
    return bool(
        str(report.get("status") or "").strip().upper() == "HEALTHY"
        and broker.get("account_ready") is True
        and broker.get("execution_snapshot_ready") is True
        and endpoint_port in _VALID_PAPER_ENDPOINT_PORTS
        and broker.get("reconciliation_next_action") == "RECONCILIATION_EVIDENCE_IS_CLEAN"
        and type(blocker_count) is int
        and blocker_count == 0
        and broker.get("all_open_orders_ready") is True
        and type(open_order_count) is int
        and open_order_count == 0
        and isinstance(open_orders, list)
        and len(open_orders) == 0
        and report.get("accounting_safe") is True
        and report.get("risk_safe") is True
        and report.get("monitor_order_sent") is False
        and report.get("live_order_sent") is False
    )


def _cash_gate(
    *,
    ticker: str,
    readiness_report: dict | None,
    account_report: dict | None,
) -> tuple[float | None, float | None, bool, str | None, float | None, float | None, bool, list[str]]:
    blockers: list[str] = []
    currency = _INSTRUMENT_CURRENCY.get(ticker)
    if currency is None or not isinstance(readiness_report, dict) or not isinstance(account_report, dict):
        return None, None, False, currency, None, None, False, [
            "same-run cash evidence cannot be derived"
        ]

    notional_jpy = _positive(readiness_report.get("estimated_notional_jpy"))
    limit_price = _positive(readiness_report.get("limit_price"))
    try:
        quantity = int(readiness_report.get("quantity"))
    except (TypeError, ValueError):
        quantity = 0
    native_notional = limit_price * quantity if limit_price is not None and quantity > 0 else None

    available = _finite(account_report.get("available_funds"))
    required_available = (
        notional_jpy + _BASE_AVAILABLE_FUNDS_RESERVE_JPY
        if notional_jpy is not None
        else None
    )
    available_ready = bool(
        available is not None
        and required_available is not None
        and available >= required_available
    )
    if not available_ready:
        blockers.append("Live available funds do not cover pilot notional plus JPY reserve")

    balances = account_report.get("settled_cash_by_currency")
    balances = balances if isinstance(balances, dict) else {}
    settled = _finite(balances.get(currency))
    reserve = _SETTLED_CASH_RESERVE.get(currency)
    required_settled = (
        native_notional + reserve
        if native_notional is not None and reserve is not None
        else None
    )
    settled_ready = bool(
        settled is not None
        and required_settled is not None
        and settled >= required_settled
    )
    if not settled_ready:
        blockers.append(
            f"settled {currency} cash does not cover LIMIT value plus first-pilot reserve"
        )

    return (
        available,
        required_available,
        available_ready,
        currency,
        settled,
        required_settled,
        settled_ready,
        blockers,
    )


def evaluate_live_pilot_same_run_preflight(
    *,
    ticker: str,
    expected_account_fingerprint: str,
    readiness_report: dict | None,
    live_account_report: dict | None,
    live_open_orders_report: dict | None,
    live_fx_report: dict | None,
    paper_monitor_report: dict | None,
    settings: PlatformSettings = SETTINGS,
    stop_path: Path = DEFAULT_STOP_PATH,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    max_skew_seconds: float = DEFAULT_MAX_SKEW_SECONDS,
) -> LivePilotSameRunPreflight:
    current = _now_utc(now)
    for name, value in (
        ("max_age_seconds", max_age_seconds),
        ("max_skew_seconds", max_skew_seconds),
    ):
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be positive and finite") from exc
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError(f"{name} must be positive and finite")

    normalized_ticker = str(ticker or "").strip().upper()
    expected_fingerprint = str(expected_account_fingerprint or "").strip().lower()
    blockers: list[str] = []

    readiness_ready = bool(
        isinstance(readiness_report, dict)
        and readiness_report.get("operational_pilot_ready") is True
        and readiness_report.get("status") == "READY_FOR_ONE_OPERATIONAL_PILOT"
        and str(readiness_report.get("ticker") or "").strip().upper() == normalized_ticker
        and readiness_report.get("order_sent") is False
        and readiness_report.get("live_order_sent") is False
    )
    if not readiness_ready:
        blockers.append("operational Live pilot readiness is not ready for this ticker")

    account_clean = _read_only_clean(live_account_report)
    open_orders_clean = _read_only_clean(live_open_orders_report)
    if not account_clean:
        blockers.append("same-run Live account evidence is not clean read-only evidence")
    if not open_orders_clean:
        blockers.append("same-run Live open-order evidence is not clean read-only evidence")
    if open_orders_clean:
        raw_count = live_open_orders_report.get("open_order_count")
        raw_orders = live_open_orders_report.get("orders")
        if type(raw_count) is not int or raw_count != 0 or not isinstance(raw_orders, list) or raw_orders:
            blockers.append("same-run Live open-order evidence is not exactly empty")

    observed_fingerprint = (
        str(live_account_report.get("account_fingerprint") or "").strip().lower()
        if isinstance(live_account_report, dict)
        else ""
    )
    open_orders_fingerprint = (
        str(live_open_orders_report.get("account_fingerprint") or "").strip().lower()
        if isinstance(live_open_orders_report, dict)
        else ""
    )
    fingerprint_match = bool(
        expected_fingerprint
        and len(expected_fingerprint) == 64
        and observed_fingerprint == expected_fingerprint
        and open_orders_fingerprint == expected_fingerprint
    )
    if not fingerprint_match:
        blockers.append("same-run Live account/open-order fingerprints do not match the pinned account")

    account_port = _port(live_account_report)
    open_orders_port = _port(live_open_orders_report)
    required_ports = [account_port, open_orders_port]
    if account_port is None or open_orders_port is None:
        blockers.append("same-run Live endpoint is missing or not an audited Live port")

    fx_required = normalized_ticker in _USD_TICKERS
    fx_clean = True
    fx_port: int | None = None
    if fx_required:
        fx_clean = bool(
            _read_only_clean(live_fx_report)
            and str(live_fx_report.get("base_currency") or "").strip().upper() == "USD"
            and str(live_fx_report.get("quote_currency") or "").strip().upper() == "JPY"
        )
        fx_port = _port(live_fx_report)
        required_ports.append(fx_port)
        if not fx_clean:
            blockers.append("same-run Live USD/JPY evidence is not clean read-only evidence")
        if fx_port is None:
            blockers.append("same-run Live FX endpoint is missing or not an audited Live port")

    endpoint_binding_ready = bool(
        required_ports
        and all(port is not None for port in required_ports)
        and len(set(required_ports)) == 1
    )
    endpoint_port = account_port if endpoint_binding_ready else None
    if not endpoint_binding_ready:
        blockers.append("same-run Live evidence is mixed across different endpoints")

    timestamp_reports: list[tuple[str, dict | None]] = [
        ("readiness", readiness_report),
        ("account", live_account_report),
        ("open_orders", live_open_orders_report),
        ("paper_monitor", paper_monitor_report),
    ]
    if fx_required:
        timestamp_reports.append(("fx", live_fx_report))

    observed_times: list[datetime] = []
    evidence_fresh = True
    for label, report in timestamp_reports:
        observed = _timestamp(report.get("checked_at") if isinstance(report, dict) else None)
        if observed is None:
            evidence_fresh = False
            blockers.append(f"{label} evidence has no timezone-aware checked_at")
            continue
        age = (current - observed).total_seconds()
        if age < 0 or age > float(max_age_seconds):
            evidence_fresh = False
            blockers.append(f"{label} evidence is outside the same-run freshness window")
        observed_times.append(observed)

    skew_seconds: float | None = None
    if observed_times:
        skew_seconds = (max(observed_times) - min(observed_times)).total_seconds()
        if skew_seconds > float(max_skew_seconds):
            evidence_fresh = False
            blockers.append("same-run evidence timestamps are too far apart")
    else:
        evidence_fresh = False

    (
        available_funds_jpy,
        required_available_funds_jpy,
        available_funds_ready,
        settled_cash_currency,
        settled_cash_amount,
        required_settled_cash_amount,
        settled_cash_ready,
        cash_blockers,
    ) = _cash_gate(
        ticker=normalized_ticker,
        readiness_report=readiness_report,
        account_report=live_account_report,
    )
    blockers.extend(cash_blockers)

    paper_safe = _paper_safe(paper_monitor_report)
    if not paper_safe:
        blockers.append("same-run Paper safety evidence is not clean")

    emergency_clear = not live_pilot_stop_is_active(settings=settings, stop_path=stop_path)
    if not emergency_clear:
        blockers.append("Live pilot emergency stop is active")

    live_lock_intact = bool(
        not settings.enable_live_trading
        and not settings.live_trading_unlocked
        and isinstance(readiness_report, dict)
        and readiness_report.get("live_global_lock_intact_during_preparation") is True
    )
    if not live_lock_intact:
        blockers.append("global Live Trading lock is not intact during preparation")

    ready = not blockers
    return LivePilotSameRunPreflight(
        status="READY_FOR_OPERATOR_AUTHORIZATION" if ready else "BLOCKED",
        checked_at=current.isoformat(timespec="seconds"),
        blockers=tuple(blockers),
        ticker=normalized_ticker,
        account_fingerprint=expected_fingerprint if fingerprint_match else "",
        account_fingerprint_match=fingerprint_match,
        endpoint_port=endpoint_port,
        endpoint_binding_ready=endpoint_binding_ready,
        evidence_fresh=evidence_fresh,
        evidence_skew_seconds=skew_seconds,
        operational_readiness_ready=readiness_ready,
        paper_monitor_safe=paper_safe,
        emergency_stop_clear=emergency_clear,
        live_global_lock_intact=live_lock_intact,
        ready=ready,
        available_funds_jpy=available_funds_jpy,
        required_available_funds_jpy=required_available_funds_jpy,
        available_funds_ready=available_funds_ready,
        settled_cash_currency=settled_cash_currency,
        settled_cash_amount=settled_cash_amount,
        required_settled_cash_amount=required_settled_cash_amount,
        settled_cash_ready=settled_cash_ready,
    )


def preflight_record(result: LivePilotSameRunPreflight) -> dict:
    return {
        "schema_version": 3,
        **asdict(result),
        "cash_policy": {
            "base_available_funds_reserve_jpy": _BASE_AVAILABLE_FUNDS_RESERVE_JPY,
            "settled_cash_reserve_by_currency": dict(_SETTLED_CASH_RESERVE),
            "interpretation": "operational safety reserve, not a commission estimate",
        },
        "interpretation": (
            "This only proves a fresh, internally consistent read-only pre-send snapshot, "
            "including prepared settled instrument cash. It does not authorize or transmit "
            "a Live order."
        ),
    }
