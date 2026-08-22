"""Fail-closed one-shot coordinator for closing one SPY Paper share in extended hours."""
from __future__ import annotations

from ai_asset_platform.brokers.ibkr_account_snapshot import preview_ibkr_paper_account_snapshot
from ai_asset_platform.brokers.ibkr_close_cycle import CloseCyclePlan, build_close_cycle_plan
from ai_asset_platform.brokers.ibkr_extended_close_e2e import (
    ExtendedPaperCloseResult,
    run_spy_extended_paper_close,
)


def run_extended_close_cycle() -> tuple[CloseCyclePlan, ExtendedPaperCloseResult | None]:
    snapshot = preview_ibkr_paper_account_snapshot()
    plan = build_close_cycle_plan(snapshot)
    if not plan.ready or plan.limit_price is None:
        return plan, None
    result = run_spy_extended_paper_close(limit_price=plan.limit_price)
    return plan, result


def main() -> int:
    plan, result = run_extended_close_cycle()
    print("===== IBKR PAPER SPY EXTENDED-HOURS CLOSE CYCLE =====")
    print("PLAN READY             :", plan.ready)
    print("PLAN REASON            :", plan.reason)
    print("BROKER SPY QTY         :", plan.broker_quantity)
    print("BROKER MARKET PRICE    :", plan.broker_market_price)
    print("AUTO LIMIT PRICE       :", plan.limit_price)
    print("CLOSE ATTEMPTED        :", bool(result and result.attempted))
    print("CLOSE REASON           :", getattr(result, "reason", None))
    print("FILL PERSISTED         :", bool(result and result.confirmed_fill_persisted))
    print("REAL LIVE ORDER SENT   : False")
    if result is None:
        return 2
    return 0 if result.confirmed_fill_persisted else (1 if result.attempted else 2)


if __name__ == "__main__":
    raise SystemExit(main())
