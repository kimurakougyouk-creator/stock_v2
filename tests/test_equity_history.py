from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.reports.equity_history import (
    EquityPoint,
    append_equity_history,
    calculate_equity_curve,
    calculate_maximum_drawdown,
    load_equity_history,
    replay_fills_to_equity,
)


def test_equity_curve_and_drawdown_use_total_assets():
    points = [
        EquityPoint("t1", "a", 0, 0, 1000),
        EquityPoint("t2", "b", 0, 0, 1200),
        EquityPoint("t3", "c", 0, 0, 900),
        EquityPoint("t4", "d", 0, 0, 1100),
    ]
    curve = calculate_equity_curve(points)
    assert curve == [1000.0, 1200.0, 900.0, 1100.0]
    assert calculate_maximum_drawdown(curve) == 300.0


def test_append_is_idempotent_by_order_intent_id(tmp_path):
    path = tmp_path / "equity.csv"
    point = EquityPoint("t1", "intent-1", 900, 100, 1000)
    assert append_equity_history(path, point) is True
    assert append_equity_history(path, point) is False
    assert load_equity_history(path) == [point]


def test_replay_fill_does_not_double_count_same_intent():
    fill = FillResult(
        order_id="1",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=1,
        fill_price=100.0,
    )
    points = replay_fills_to_equity(
        initial_cash=1000.0,
        fills=[("intent-1", fill), ("intent-1", fill)],
        market_prices={"AAPL": 110.0},
    )
    assert len(points) == 1
    assert points[0].cash == 900.0
    assert points[0].market_value == 110.0
    assert points[0].total_assets == 1010.0
