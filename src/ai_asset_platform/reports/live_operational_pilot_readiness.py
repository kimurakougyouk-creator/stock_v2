"""Fail-closed readiness for one tiny operational IBKR Live pilot.

This gate deliberately separates two questions:

1. Can one tightly bounded real-cash order be used to validate Live execution
   mechanics safely?
2. Is the strategy proven enough for normal/expanded Live deployment?

The first does **not** require statistically proven profitability; otherwise a
small operational pilot could never be used to validate the Paper-vs-Live
execution gap. The second still requires the existing fee-aware/net-profitability
readiness gate. This module is read-only and sends no order.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from ai_asset_platform.core.settings import SETTINGS, PlatformSettings
from ai_asset_platform.execution.verified_market_session import (
    VerifiedMarketSessionResult,
    evaluate_verified_market_session,
)


DEFAULT_LIVE_ACCOUNT_REPORT = Path("results/ibkr_live_readonly_account_latest.json")
DEFAULT_LIVE_OPEN_ORDERS_REPORT = Path("results/ibkr_live_all_open_orders_latest.json")
DEFAULT_PAPER_MONITOR_REPORT = Path("results/ibkr_paper_operations_monitor_latest.json")
DEFAULT_STRATEGY_DEPLOYMENT_REPORT = Path("results/live_cash_readiness_latest.json")
DEFAULT_REPORT_PATH = Path("results/live_operational_pilot_readiness_latest.json")
REPORT_SCHEMA_VERSION = 1

# Absolute ceiling for the very first operational Live order. The operator may
# choose a lower limit later, but code cannot exceed this first-pilot ceiling.
ABSOLUTE_FIRST_PILOT_NOTIONAL_JPY = 50_000.0

# Keep the first Live pilot inside the exact stock/ETF quantities already proven
# through the controlled IBKR Paper path. This is an operational boundary, not a
# claim that Live execution is already verified.
LIVE_PILOT_SCOPE = {
    "AAPL": 1,
    "SPY": 1,
    "9432.T": 100,
}


@dataclass(frozen=True)
class LiveOperationalPilotReadiness:
    status: str
    blockers: tuple[str, ...]
    ticker: str
    side: str
    quantity: int
    estimated_notional_jpy: float | None
    absolute_notional_ceiling_jpy: float
    live_account_ready: bool
    live_account_fingerprint_match: bool
    live_open_orders_ready: bool
    live_open_order_count: int | None
    target_live_position_quantity: float | None
    paper_monitor_safe: bool
    market_session_allowed: bool
    market_session: str | None
    live_global_lock_intact_during_preparation: bool
    operational_pilot_ready: bool
    strategy_deployment_ready: bool
    broker_connection_used: bool = False
    order_sent: bool = False
    live_order_sent: bool = False


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _normalized_ticker(value: object) -> str:
    return str(value or "").strip().upper()


def _target_position_quantity(account_report: dict, ticker: str) -> float | None:
    positions = account_report.get("positions")
    if not isinstance(positions, list):
        return None
    normalized = _normalized_ticker(ticker)
    if normalized == "9432.T":
        expected_symbol, expected_currency = "9432", "JPY"
    else:
        expected_symbol, expected_currency = normalized, "USD"
    total = 0.0
    matched = False
    for row in positions:
        if not isinstance(row, dict):
            continue
        symbol = _normalized_ticker(row.get("symbol"))
        sec_type = _normalized_ticker(row.get("sec_type"))
        currency = _normalized_ticker(row.get("currency"))
        if symbol != expected_symbol or sec_type != "STK" or currency != expected_currency:
            continue
        try:
            quantity = float(row.get("quantity"))
        except (TypeError, ValueError):
            return None
        if quantity != quantity or quantity in {float("inf"), float("-inf")}:
            return None
        matched = True
        total += quantity
    return total if matched else 0.0


def _paper_monitor_safe(report: dict | None) -> bool:
    if not isinstance(report, dict):
        return False
    status = str(report.get("status") or "").strip().upper()
    broker = report.get("broker")
    broker = broker if isinstance(broker, dict) else {}
    try:
        blockers = int(broker.get("reconciliation_blocker_count", 0) or 0)
        open_orders = int(broker.get("open_order_count", 0) or 0)
    except (TypeError, ValueError):
        return False
    return (
        status != "CRITICAL"
        and bool(report.get("accounting_safe"))
        and bool(report.get("risk_safe"))
        and blockers == 0
        and open_orders == 0
        and not bool(report.get("monitor_order_sent"))
        and not bool(report.get("live_order_sent"))
    )


def evaluate_live_operational_pilot_readiness(
    *,
    ticker: str,
    side: str,
    quantity: int,
    estimated_notional_jpy: float | None,
    expected_account_fingerprint: str | None,
    live_account_report: dict | None,
    live_open_orders_report: dict | None,
    paper_monitor_report: dict | None,
    strategy_deployment_report: dict | None = None,
    settings: PlatformSettings = SETTINGS,
    market_session: VerifiedMarketSessionResult | None = None,
) -> LiveOperationalPilotReadiness:
    blockers: list[str] = []
    normalized_ticker = _normalized_ticker(ticker)
    normalized_side = str(side or "").strip().upper()
    try:
        normalized_quantity = int(quantity)
    except (TypeError, ValueError):
        normalized_quantity = 0

    verified_quantity = LIVE_PILOT_SCOPE.get(normalized_ticker)
    if verified_quantity is None:
        blockers.append("ticker is outside the exact first-Live-pilot scope")
    elif normalized_quantity != verified_quantity:
        blockers.append(
            f"quantity must equal the bounded pilot quantity {verified_quantity}"
        )
    if normalized_side not in {"BUY", "SELL"}:
        blockers.append("side must be BUY or SELL")

    notional: float | None = None
    if estimated_notional_jpy is not None:
        try:
            notional = float(estimated_notional_jpy)
        except (TypeError, ValueError):
            notional = None
    if notional is None or notional <= 0 or notional != notional:
        blockers.append("verified estimated notional in JPY is missing")
    elif notional > ABSOLUTE_FIRST_PILOT_NOTIONAL_JPY:
        blockers.append(
            "estimated notional exceeds the absolute first-pilot ceiling"
        )

    live_lock_intact = (
        not bool(settings.enable_live_trading)
        and not bool(settings.live_trading_unlocked)
    )
    if not live_lock_intact:
        blockers.append("global Live Trading lock must remain closed during preparation")

    account_ready = bool(
        isinstance(live_account_report, dict)
        and live_account_report.get("ready") is True
        and live_account_report.get("connection_mode") == "LIVE_READ_ONLY"
        and not live_account_report.get("order_sent")
        and not live_account_report.get("live_order_sent")
    )
    if not account_ready:
        blockers.append("Live read-only account preflight is not ready")

    observed_fingerprint = (
        str(live_account_report.get("account_fingerprint") or "").strip()
        if isinstance(live_account_report, dict)
        else ""
    )
    expected_fingerprint = str(expected_account_fingerprint or "").strip()
    fingerprint_match = bool(
        expected_fingerprint
        and observed_fingerprint
        and expected_fingerprint == observed_fingerprint
    )
    if not fingerprint_match:
        blockers.append("Live account fingerprint is not pinned/matched")

    account_currency = (
        str(live_account_report.get("base_currency") or "").strip().upper()
        if isinstance(live_account_report, dict)
        else ""
    )
    if account_ready and account_currency != str(settings.account_currency).strip().upper():
        blockers.append("Live account base currency differs from configured account currency")

    target_position = (
        _target_position_quantity(live_account_report, normalized_ticker)
        if isinstance(live_account_report, dict) and normalized_ticker
        else None
    )
    if normalized_side == "BUY" and target_position not in {0.0}:
        blockers.append("first-pilot BUY requires the target Live position to be flat")
    if normalized_side == "SELL":
        if target_position is None or verified_quantity is None:
            blockers.append("first-pilot SELL target position cannot be verified")
        elif target_position != float(verified_quantity):
            blockers.append("first-pilot SELL requires the exact bounded target position")

    open_orders_ready = bool(
        isinstance(live_open_orders_report, dict)
        and live_open_orders_report.get("ready") is True
        and live_open_orders_report.get("connection_mode") == "LIVE_READ_ONLY"
        and not live_open_orders_report.get("order_sent")
        and not live_open_orders_report.get("cancel_sent")
        and not live_open_orders_report.get("live_order_sent")
    )
    open_order_count: int | None = None
    if open_orders_ready:
        try:
            open_order_count = int(live_open_orders_report.get("open_order_count", 0))
        except (TypeError, ValueError):
            open_order_count = None
    if not open_orders_ready:
        blockers.append("Live all-open-orders preflight is not ready")
    elif open_order_count != 0:
        blockers.append("unexpected open Live orders exist")

    paper_safe = _paper_monitor_safe(paper_monitor_report)
    if not paper_safe:
        blockers.append("existing Paper safety monitor evidence is not clean")

    session = market_session or (
        evaluate_verified_market_session(normalized_ticker)
        if normalized_ticker
        else None
    )
    session_allowed = bool(session and session.allowed)
    if not session_allowed:
        blockers.append("target market session is not currently open/audited")

    strategy_ready = bool(
        isinstance(strategy_deployment_report, dict)
        and strategy_deployment_report.get("ready_for_live_cash") is True
    )

    ready = not blockers
    return LiveOperationalPilotReadiness(
        status="READY_FOR_ONE_OPERATIONAL_PILOT" if ready else "BLOCKED",
        blockers=tuple(blockers),
        ticker=normalized_ticker,
        side=normalized_side,
        quantity=normalized_quantity,
        estimated_notional_jpy=notional,
        absolute_notional_ceiling_jpy=ABSOLUTE_FIRST_PILOT_NOTIONAL_JPY,
        live_account_ready=account_ready,
        live_account_fingerprint_match=fingerprint_match,
        live_open_orders_ready=open_orders_ready,
        live_open_order_count=open_order_count,
        target_live_position_quantity=target_position,
        paper_monitor_safe=paper_safe,
        market_session_allowed=session_allowed,
        market_session=(session.session if session else None),
        live_global_lock_intact_during_preparation=live_lock_intact,
        operational_pilot_ready=ready,
        strategy_deployment_ready=strategy_ready,
    )


def readiness_record(result: LiveOperationalPilotReadiness) -> dict:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        **asdict(result),
        "broker_connection_used": False,
        "order_sent": False,
        "live_order_sent": False,
        "interpretation": (
            "Operational-pilot readiness validates one bounded execution-mechanics test only. "
            "It is not evidence that normal Live strategy deployment is profitable or approved."
        ),
    }


def audit_live_operational_pilot_readiness(
    *,
    ticker: str,
    side: str,
    quantity: int,
    estimated_notional_jpy: float | None,
    expected_account_fingerprint: str | None,
    settings: PlatformSettings = SETTINGS,
) -> LiveOperationalPilotReadiness:
    def safe_load(path: Path) -> dict | None:
        try:
            return _load_json(path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return None

    return evaluate_live_operational_pilot_readiness(
        ticker=ticker,
        side=side,
        quantity=quantity,
        estimated_notional_jpy=estimated_notional_jpy,
        expected_account_fingerprint=expected_account_fingerprint,
        live_account_report=safe_load(DEFAULT_LIVE_ACCOUNT_REPORT),
        live_open_orders_report=safe_load(DEFAULT_LIVE_OPEN_ORDERS_REPORT),
        paper_monitor_report=safe_load(DEFAULT_PAPER_MONITOR_REPORT),
        strategy_deployment_report=safe_load(DEFAULT_STRATEGY_DEPLOYMENT_REPORT),
        settings=settings,
    )


def persist_live_operational_pilot_readiness(
    result: LiveOperationalPilotReadiness,
    *, report_path: Path = DEFAULT_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(readiness_record(result), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)
