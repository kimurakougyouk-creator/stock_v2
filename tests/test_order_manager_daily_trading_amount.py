from datetime import datetime

import order_manager


def test_calculate_daily_trading_amount_sums_today_buy_and_sell(
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
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
            {
                "created_at": today,
                "ticker": "6758.T",
                "side": "SELL",
                "shares": 50,
                "reference_price": 12000.0,
            },
        ],
    )

    assert order_manager.calculate_daily_trading_amount() == 850_000.0


def test_calculate_daily_trading_amount_ignores_other_days(
    monkeypatch,
):
    monkeypatch.setattr(
        order_manager,
        "load_paper_orders",
        lambda: [
            {
                "created_at": "2000-01-01T10:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
        ],
    )

    assert order_manager.calculate_daily_trading_amount() == 0.0


def test_calculate_daily_trading_amount_ignores_invalid_orders(
    monkeypatch,
):
    today = datetime.now().isoformat(timespec="seconds")

    monkeypatch.setattr(
        order_manager,
        "load_paper_orders",
        lambda: [
            {
                "created_at": today,
                "side": "HOLD",
                "shares": 100,
                "reference_price": 1000.0,
            },
            {
                "created_at": today,
                "side": "BUY",
                "shares": 0,
                "reference_price": 1000.0,
            },
            {
                "created_at": today,
                "side": "SELL",
                "shares": 100,
                "reference_price": 0,
            },
            {
                "created_at": "invalid-date",
                "side": "BUY",
                "shares": 100,
                "reference_price": 1000.0,
            },
        ],
    )

    assert order_manager.calculate_daily_trading_amount() == 0.0
