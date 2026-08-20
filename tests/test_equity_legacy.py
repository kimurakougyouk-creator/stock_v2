from ai_asset_platform.reports.equity_legacy import legacy_orders_to_equity


def test_legacy_orders_to_equity_is_idempotent_by_order_intent_id():
    order = {
        "ticker": "AAPL",
        "side": "BUY",
        "shares": 1,
        "reference_price": 100.0,
        "order_intent_id": "intent-1",
    }
    points = legacy_orders_to_equity(
        [order, dict(order)],
        initial_cash=1000.0,
        market_prices={"AAPL": 110.0},
    )
    assert len(points) == 1
    assert points[0].cash == 900.0
    assert points[0].market_value == 110.0
    assert points[0].total_assets == 1010.0


def test_legacy_orders_without_intent_are_kept_as_distinct_historical_rows():
    orders = [
        {"ticker": "AAPL", "side": "BUY", "shares": 1, "reference_price": 100.0},
        {"ticker": "AAPL", "side": "BUY", "shares": 1, "reference_price": 100.0},
    ]
    points = legacy_orders_to_equity(
        orders,
        initial_cash=1000.0,
        market_prices={"AAPL": 100.0},
    )
    assert len(points) == 2
    assert points[-1].total_assets == 1000.0
