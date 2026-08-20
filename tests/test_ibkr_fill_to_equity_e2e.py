import json

from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
from ai_asset_platform.reports import append_equity_history, legacy_orders_to_equity


def test_confirmed_fill_to_equity_is_idempotent_without_sending_order(tmp_path):
    order_log = tmp_path / "paper_orders.jsonl"
    equity_path = tmp_path / "equity_history.csv"

    first = record_confirmed_fill(
        ticker="AAPL",
        side="BUY",
        filled_quantity=1,
        avg_fill_price=100.0,
        order_intent_id="intent-1",
        order_log_path=order_log,
    )
    second = record_confirmed_fill(
        ticker="AAPL",
        side="BUY",
        filled_quantity=1,
        avg_fill_price=100.0,
        order_intent_id="intent-1",
        order_log_path=order_log,
    )
    assert first == second

    rows = [json.loads(line) for line in order_log.read_text().splitlines()]
    assert len(rows) == 1
    points = legacy_orders_to_equity(
        rows,
        initial_cash=1000.0,
        market_prices={"AAPL": 110.0},
    )
    assert len(points) == 1
    assert points[0].total_assets == 1010.0
    assert append_equity_history(equity_path, points[0]) is True
    assert append_equity_history(equity_path, points[0]) is False
