"""Fail-closed readiness evidence for a future real-cash pilot.

This module is deliberately read-only. It never connects to IBKR, never sends
Paper/Live orders, and never unlocks Live Trading. It only combines existing
local evidence into an explicit go/no-go record so a calendar date alone can
never authorize real-money trading.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from ai_asset_platform.core.settings import SETTINGS, PlatformSettings


DEFAULT_STRATEGY_REPORT_PATH = Path(
    "results/strategy_profitability_evidence_latest.json"
)
DEFAULT_MONITOR_REPORT_PATH = Path(
    "results/ibkr_paper_operations_monitor_latest.json"
)
DEFAULT_READINESS_REPORT_PATH = Path(
    "results/live_cash_readiness_latest.json"
)
REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LiveCashReadiness:
    status: str
    blockers: tuple[str, ...]
    live_safety_lock_intact: bool
    strategy_report_present: bool
    fees_accounted: bool
    net_profitability_proven: bool
    natural_closed_trade_count: int
    paper_monitor_present: bool
    paper_monitor_status: str | None
    accounting_safe: bool
    risk_safe: bool
    reconciliation_blocker_count: int | None
    open_order_count: int | None
    live_transport_implemented: bool
    broker_connection_used: bool = False
    order_sent: bool = False
    live_order_sent: bool = False

    @property
    def ready_for_live_cash(self) -> bool:
        return not self.blockers


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def evaluate_live_cash_readiness(
    *,
    strategy_report: dict | None,
    monitor_report: dict | None,
    settings: PlatformSettings = SETTINGS,
    live_transport_implemented: bool = False,
) -> LiveCashReadiness:
    """Return fail-closed evidence for whether a real-cash pilot may be designed.

    ``live_transport_implemented`` defaults to False on purpose. A future Live
    transport must be implemented and independently audited before this gate can
    ever pass. This function does not implement or enable that transport.
    """
    blockers: list[str] = []

    lock_intact = not bool(settings.enable_live_trading) and not bool(
        settings.live_trading_unlocked
    )
    if not lock_intact:
        blockers.append(
            "Live Trading safety lock is not intact during preparation"
        )

    strategy_present = isinstance(strategy_report, dict)
    fees_accounted = bool(strategy_report.get("fees_accounted")) if strategy_present else False
    net_profitability_proven = (
        bool(strategy_report.get("net_profitability_proven"))
        if strategy_present
        else False
    )
    closed_trades = (
        int(strategy_report.get("closed_trade_count", 0) or 0)
        if strategy_present
        else 0
    )

    if not strategy_present:
        blockers.append("natural-strategy profitability report is missing")
    else:
        if closed_trades <= 0:
            blockers.append("no natural closed strategy trade is proven yet")
        if not fees_accounted:
            blockers.append("commissions/fees are not durably accounted")
        if not net_profitability_proven:
            blockers.append("net strategy profitability is not proven")

    monitor_present = isinstance(monitor_report, dict)
    monitor_status = (
        str(monitor_report.get("status") or "").strip().upper()
        if monitor_present
        else None
    )
    accounting_safe = bool(monitor_report.get("accounting_safe")) if monitor_present else False
    risk_safe = bool(monitor_report.get("risk_safe")) if monitor_present else False
    broker = monitor_report.get("broker") if monitor_present else None
    broker = broker if isinstance(broker, dict) else {}
    reconciliation_blockers = (
        int(broker.get("reconciliation_blocker_count", 0) or 0)
        if monitor_present
        else None
    )
    open_orders = (
        int(broker.get("open_order_count", 0) or 0)
        if monitor_present
        else None
    )

    if not monitor_present:
        blockers.append("latest strict Paper operations monitor report is missing")
    else:
        if monitor_status == "CRITICAL":
            blockers.append("Paper operations monitor is CRITICAL")
        if not accounting_safe:
            blockers.append("Paper accounting is not safe")
        if not risk_safe:
            blockers.append("Paper risk state is not safe")
        if reconciliation_blockers != 0:
            blockers.append("Paper reconciliation has blockers")
        if open_orders != 0:
            blockers.append("unexpected open Paper orders exist")
        if bool(monitor_report.get("monitor_order_sent")):
            blockers.append("read-only monitor unexpectedly reported an order")
        if bool(monitor_report.get("live_order_sent")):
            blockers.append("monitor evidence reports a Live order")

    if not live_transport_implemented:
        blockers.append(
            "audited real-cash transport is not implemented; Live remains fail-closed"
        )

    return LiveCashReadiness(
        status="READY" if not blockers else "BLOCKED",
        blockers=tuple(blockers),
        live_safety_lock_intact=lock_intact,
        strategy_report_present=strategy_present,
        fees_accounted=fees_accounted,
        net_profitability_proven=net_profitability_proven,
        natural_closed_trade_count=closed_trades,
        paper_monitor_present=monitor_present,
        paper_monitor_status=monitor_status,
        accounting_safe=accounting_safe,
        risk_safe=risk_safe,
        reconciliation_blocker_count=reconciliation_blockers,
        open_order_count=open_orders,
        live_transport_implemented=bool(live_transport_implemented),
    )


def readiness_record(result: LiveCashReadiness) -> dict:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        **asdict(result),
        "ready_for_live_cash": result.ready_for_live_cash,
        "broker_connection_used": False,
        "order_sent": False,
        "live_order_sent": False,
    }


def audit_live_cash_readiness(
    *,
    strategy_report_path: Path = DEFAULT_STRATEGY_REPORT_PATH,
    monitor_report_path: Path = DEFAULT_MONITOR_REPORT_PATH,
    settings: PlatformSettings = SETTINGS,
    live_transport_implemented: bool = False,
) -> LiveCashReadiness:
    try:
        strategy_report = _load_json(strategy_report_path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        strategy_report = None
    try:
        monitor_report = _load_json(monitor_report_path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        monitor_report = None
    return evaluate_live_cash_readiness(
        strategy_report=strategy_report,
        monitor_report=monitor_report,
        settings=settings,
        live_transport_implemented=live_transport_implemented,
    )


def persist_live_cash_readiness(
    result: LiveCashReadiness,
    *,
    report_path: Path = DEFAULT_READINESS_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(readiness_record(result), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def main() -> int:
    result = audit_live_cash_readiness()
    persist_live_cash_readiness(result)
    print("===== LIVE CASH READINESS =====")
    print("STATUS                 :", result.status)
    print("READY FOR LIVE CASH    :", result.ready_for_live_cash)
    print("LIVE SAFETY LOCK       :", result.live_safety_lock_intact)
    print("NATURAL CLOSED TRADES  :", result.natural_closed_trade_count)
    print("FEES ACCOUNTED         :", result.fees_accounted)
    print("NET PROFIT PROVEN      :", result.net_profitability_proven)
    print("PAPER MONITOR STATUS   :", result.paper_monitor_status)
    print("ACCOUNTING SAFE        :", result.accounting_safe)
    print("RISK SAFE              :", result.risk_safe)
    print("RECON BLOCKERS         :", result.reconciliation_blocker_count)
    print("OPEN ORDERS            :", result.open_order_count)
    print("LIVE TRANSPORT         :", result.live_transport_implemented)
    print("BROKER CONNECTION USED : False")
    print("ORDER SENT             : False")
    print("LIVE ORDER SENT        : False")
    for blocker in result.blockers:
        print("BLOCKER                :", blocker)
    print("REPORT                 :", DEFAULT_READINESS_REPORT_PATH)
    return 0 if result.ready_for_live_cash else 1


if __name__ == "__main__":
    raise SystemExit(main())
