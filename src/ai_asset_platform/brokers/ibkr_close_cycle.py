"""One-shot, fail-closed SPY Paper close-cycle coordinator.

This helper never opens exposure. It reads the current broker Paper account,
requires exactly one SPY share, derives a conservative LIMIT price from the
broker-reported SPY market price, runs the dedicated position-reducing close,
and returns evidence for a follow-up read-only checkpoint. Live Trading remains
prohibited by the underlying close path.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_overnight_close_e2e import (
    OvernightPaperCloseResult,
    run_spy_overnight_paper_close,
)


@dataclass(frozen=True)
class CloseCyclePlan:
    ready: bool
    reason: str
    broker_quantity: float
    broker_market_price: float | None
    limit_price: float | None


def build_close_cycle_plan(snapshot: IbkrPaperAccountSnapshot) -> CloseCyclePlan:
    if not snapshot.ready:
        return CloseCyclePlan(False, "broker Paper account snapshot is not ready", 0.0, None, None)

    positions = [
        item for item in snapshot.positions
        if item.symbol == "SPY" and item.sec_type in {"STK", "ETF"}
    ]
    quantity = float(sum(item.quantity for item in positions))
    if quantity != 1.0:
        return CloseCyclePlan(False, f"SPY close requires exactly one broker-held share; found {quantity:g}", quantity, None, None)

    prices = [float(item.market_price) for item in positions if float(item.market_price) > 0]
    if len(prices) != 1:
        return CloseCyclePlan(False, "broker SPY market price is unavailable or ambiguous", quantity, None, None)

    market_price = prices[0]
    # Position-reducing Paper SELL only. A 1% buffer below the broker-observed
    # reference improves fill probability without using an unbounded order.
    limit_price = round(max(0.01, market_price * 0.99), 2)
    return CloseCyclePlan(True, "one-share SPY Paper close plan is ready", quantity, market_price, limit_price)


def run_close_cycle() -> tuple[CloseCyclePlan, OvernightPaperCloseResult | None]:
    snapshot = preview_ibkr_paper_account_snapshot()
    plan = build_close_cycle_plan(snapshot)
    if not plan.ready or plan.limit_price is None:
        return plan, None
    result = run_spy_overnight_paper_close(limit_price=plan.limit_price)
    return plan, result


def main() -> int:
    plan, result = run_close_cycle()
    print("===== IBKR PAPER SPY CLOSE CYCLE =====")
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
