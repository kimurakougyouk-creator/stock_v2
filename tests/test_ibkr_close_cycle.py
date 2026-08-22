from types import SimpleNamespace

from ai_asset_platform.brokers.ibkr_close_cycle import build_close_cycle_plan


def _snapshot(*, ready=True, quantity=1.0, market_price=760.0):
    return SimpleNamespace(
        ready=ready,
        positions=(
            SimpleNamespace(
                symbol="SPY",
                sec_type="STK",
                quantity=quantity,
                market_price=market_price,
            ),
        ),
    )


def test_close_cycle_plan_requires_ready_broker_snapshot():
    plan = build_close_cycle_plan(_snapshot(ready=False))
    assert not plan.ready
    assert plan.limit_price is None


def test_close_cycle_plan_requires_exactly_one_spy_share():
    plan = build_close_cycle_plan(_snapshot(quantity=2.0))
    assert not plan.ready
    assert plan.broker_quantity == 2.0


def test_close_cycle_plan_requires_positive_broker_price():
    plan = build_close_cycle_plan(_snapshot(market_price=0.0))
    assert not plan.ready
    assert plan.limit_price is None


def test_close_cycle_plan_uses_bounded_one_percent_limit_buffer():
    plan = build_close_cycle_plan(_snapshot(market_price=760.0))
    assert plan.ready
    assert plan.broker_quantity == 1.0
    assert plan.broker_market_price == 760.0
    assert plan.limit_price == 752.4
