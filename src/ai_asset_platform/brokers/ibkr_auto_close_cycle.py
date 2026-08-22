"""Session-aware one-shot coordinator for closing exactly one SPY Paper share.

Chooses the currently available US Paper close route without opening exposure:
- Overnight route during the documented IBKR Overnight session.
- SMART OutsideRth route during US premarket/after-hours.
If neither session is open, no order is attempted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ai_asset_platform.brokers.ibkr_account_snapshot import preview_ibkr_paper_account_snapshot
from ai_asset_platform.brokers.ibkr_close_cycle import CloseCyclePlan, build_close_cycle_plan
from ai_asset_platform.brokers.ibkr_extended_close_e2e import (
    ExtendedPaperCloseResult,
    is_us_extended_session_open,
    run_spy_extended_paper_close,
)
from ai_asset_platform.brokers.ibkr_overnight_close_e2e import (
    OvernightPaperCloseResult,
    run_spy_overnight_paper_close,
)
from ai_asset_platform.brokers.ibkr_overnight_paper_e2e import is_ibkr_overnight_session_open


@dataclass(frozen=True)
class AutoCloseCycleResult:
    plan: CloseCyclePlan
    route: str | None
    close_result: OvernightPaperCloseResult | ExtendedPaperCloseResult | None

    @property
    def confirmed_fill_persisted(self) -> bool:
        return bool(self.close_result and self.close_result.confirmed_fill_persisted)


def choose_close_route(now: datetime | None = None) -> str | None:
    if is_ibkr_overnight_session_open(now):
        return "OVERNIGHT"
    if is_us_extended_session_open(now):
        return "EXTENDED_RTH"
    return None


def run_auto_close_cycle(now: datetime | None = None) -> AutoCloseCycleResult:
    snapshot = preview_ibkr_paper_account_snapshot()
    plan = build_close_cycle_plan(snapshot)
    if not plan.ready or plan.limit_price is None:
        return AutoCloseCycleResult(plan, None, None)

    route = choose_close_route(now)
    if route == "OVERNIGHT":
        result = run_spy_overnight_paper_close(limit_price=plan.limit_price, now=now)
        return AutoCloseCycleResult(plan, route, result)
    if route == "EXTENDED_RTH":
        result = run_spy_extended_paper_close(limit_price=plan.limit_price, now=now)
        return AutoCloseCycleResult(plan, route, result)
    return AutoCloseCycleResult(plan, None, None)


def main() -> int:
    result = run_auto_close_cycle()
    close = result.close_result
    print("===== IBKR PAPER SPY AUTO CLOSE CYCLE =====")
    print("PLAN READY             :", result.plan.ready)
    print("PLAN REASON            :", result.plan.reason)
    print("BROKER SPY QTY         :", result.plan.broker_quantity)
    print("BROKER MARKET PRICE    :", result.plan.broker_market_price)
    print("AUTO LIMIT PRICE       :", result.plan.limit_price)
    print("SELECTED ROUTE         :", result.route)
    print("CLOSE ATTEMPTED        :", bool(close and close.attempted))
    print("CLOSE REASON           :", getattr(close, "reason", "no supported close session is open" if result.route is None else None))
    print("FILL PERSISTED         :", result.confirmed_fill_persisted)
    print("REAL LIVE ORDER SENT   : False")
    if result.confirmed_fill_persisted:
        return 0
    if close is not None and close.attempted:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
