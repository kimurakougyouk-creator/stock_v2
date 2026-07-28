from datetime import datetime

import order_manager


def test_calculate_daily_sell_order_count_counts_only_today_sell_orders(
    monkeypatch,
):
    today = datetime.now().isoformat(timespec="seconds")

    monkeypatch.setattr(
        order_manager,
        "load_paper_orders",
        lambda: [
            {
                "created_at": today,
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 2500.0,
            },
            {
                "created_at": today,
                "ticker": "6758.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 12000.0,
            },
            {
                "created_at": today,
                "ticker": "8306.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 1500.0,
            },
            {
                "created_at": "2000-01-01T10:00:00",
                "ticker": "9984.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 8000.0,
            },
        ],
    )

    assert order_manager.calculate_daily_sell_order_count() == 2


def test_calculate_daily_sell_order_count_returns_zero_without_orders(
    monkeypatch,
):
    monkeypatch.setattr(
        order_manager,
        "load_paper_orders",
        lambda: [],
    )

    assert order_manager.calculate_daily_sell_order_count() == 0


def test_calculate_daily_sell_order_count_ignores_invalid_history(
    monkeypatch,
):
    today = datetime.now().isoformat(timespec="seconds")

    monkeypatch.setattr(
        order_manager,
        "load_paper_orders",
        lambda: [
            {
                "created_at": "",
                "side": "SELL",
            },
            {
                "created_at": "invalid-date",
                "side": "SELL",
            },
            {
                "created_at": today,
                "side": "sell",
            },
        ],
    )

    assert order_manager.calculate_daily_sell_order_count() == 1
