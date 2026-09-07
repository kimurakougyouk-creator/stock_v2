from datetime import date, datetime
from zoneinfo import ZoneInfo

import order_manager


def test_daily_buy_count_maps_utc_timestamp_to_tokyo_account_day(
    monkeypatch,
):
    monkeypatch.setattr(
        order_manager,
        "account_today",
        lambda settings: date(2026, 8, 22),
    )
    monkeypatch.setattr(
        order_manager,
        "load_paper_orders",
        lambda: [
            {
                "created_at": "2026-08-21T15:30:00+00:00",
                "ticker": "SPY",
                "side": "BUY",
                "shares": 1,
                "reference_price": 600.0,
            },
            {
                "created_at": "2026-08-21T14:30:00+00:00",
                "ticker": "AAPL",
                "side": "BUY",
                "shares": 1,
                "reference_price": 250.0,
            },
            {
                "created_at": "2026-08-21T15:45:00+00:00",
                "ticker": "SPY",
                "side": "SELL",
                "shares": 1,
                "reference_price": 601.0,
            },
        ],
    )

    assert order_manager.calculate_daily_buy_order_count() == 1


def test_daily_buy_count_counts_three_recorded_buys(
    monkeypatch,
):
    monkeypatch.setattr(
        order_manager,
        "account_today",
        lambda settings: date(2026, 8, 22),
    )
    monkeypatch.setattr(
        order_manager,
        "load_paper_orders",
        lambda: [
            {
                "created_at": f"2026-08-22T{hour:02d}:00:00+09:00",
                "ticker": ticker,
                "side": "BUY",
                "shares": 1,
                "reference_price": 100.0,
            }
            for hour, ticker in [(9, "A"), (10, "B"), (11, "C")]
        ],
    )

    assert order_manager.calculate_daily_buy_order_count() == 3


def test_create_paper_order_records_account_timezone_timestamp(
    tmp_path,
    monkeypatch,
):
    fixed = datetime(
        2026,
        8,
        22,
        0,
        30,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
    monkeypatch.setattr(
        order_manager,
        "account_now",
        lambda settings: fixed,
    )
    monkeypatch.setattr(
        order_manager,
        "ORDER_LOG_PATH",
        tmp_path / "paper_orders.jsonl",
    )
    monkeypatch.setattr(
        order_manager,
        "save_realized_trade_pnls",
        lambda: None,
    )

    order = order_manager.create_paper_order(
        "AAPL",
        "BUY",
        1,
        250.0,
    )

    assert order["created_at"] == "2026-08-22T00:30:00+09:00"
