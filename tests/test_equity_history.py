import csv
from ai_asset_platform.reports.equity_history import (
    EQUITY_HISTORY_FIELDS, EquityPoint, append_equity_history,
    calculate_equity_curve, calculate_maximum_drawdown, equity_point_to_record,
)


def order(side, shares, price, *, intent=None, ticker="AAPL", created_at="2026-08-20T00:00:00"):
    row = {"ticker": ticker, "side": side, "shares": shares, "reference_price": price, "created_at": created_at}
    if intent is not None:
        row["order_intent_id"] = intent
    return row


def test_empty_orders_returns_empty_curve():
    assert calculate_equity_curve([], initial_capital=1000) == []


def test_buy_keeps_equity_at_fill_price():
    points = calculate_equity_curve([order("BUY", 2, 100)], initial_capital=1000)
    assert points[-1].cash == 800
    assert points[-1].holdings == 200
    assert points[-1].total_assets == 1000


def test_sell_realizes_profit_and_updates_total_assets():
    points = calculate_equity_curve([order("BUY", 2, 100), order("SELL", 1, 120)], initial_capital=1000)
    assert points[-1].cash == 920
    assert points[-1].holdings == 120
    assert points[-1].total_assets == 1040
    assert points[-1].realized_pnl == 20


def test_last_trade_marks_remaining_position():
    points = calculate_equity_curve([order("BUY", 2, 100), order("BUY", 1, 120)], initial_capital=1000)
    assert points[-1].holdings == 360
    assert points[-1].total_assets == 1040


def test_duplicate_order_intent_is_not_double_counted():
    item = order("BUY", 1, 100, intent="same")
    points = calculate_equity_curve([item, dict(item)], initial_capital=1000)
    assert len(points) == 1
    assert points[-1].cash == 900


def test_invalid_rows_are_ignored_safely():
    points = calculate_equity_curve([{}, order("HOLD", 1, 100), order("BUY", 0, 100), order("BUY", 1, -1)], initial_capital=1000)
    assert points == []


def test_invalid_oversell_is_ignored_without_corrupting_previous_state():
    points = calculate_equity_curve([order("BUY", 1, 100), order("SELL", 2, 120)], initial_capital=1000)
    assert len(points) == 1
    assert points[0].total_assets == 1000


def test_maximum_drawdown_uses_total_assets():
    points = [
        EquityPoint("t1", 0, 0, 1000, 0, 0),
        EquityPoint("t2", 0, 0, 1200, 0, 0),
        EquityPoint("t3", 0, 0, 900, 0, 0),
        EquityPoint("t4", 0, 0, 1100, 0, 0),
    ]
    assert calculate_maximum_drawdown(points) == 300


def test_equity_point_record_has_stable_schema():
    point = EquityPoint("t", 900, 100, 1000, 0, 0)
    record = equity_point_to_record(point)
    assert list(record) == EQUITY_HISTORY_FIELDS
    assert record["total_assets"] == "1000"


def test_append_equity_history_is_idempotent_for_same_state(tmp_path):
    path = tmp_path / "equity_history.csv"
    first = EquityPoint("t1", 900, 100, 1000, 0, 0)
    same = EquityPoint("t2", 900, 100, 1000, 0, 0)
    changed = EquityPoint("t3", 800, 250, 1050, 0, 50)
    assert append_equity_history(first, path) is True
    assert append_equity_history(same, path) is False
    assert append_equity_history(changed, path) is True
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 2
    assert rows[-1]["total_assets"] == "1050"
