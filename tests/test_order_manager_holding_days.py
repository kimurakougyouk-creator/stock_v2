from __future__ import annotations

from datetime import datetime
import json

import order_manager


def _save_orders(tmp_path, monkeypatch, orders):
    order_log_path = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(
        order_manager,
        "ORDER_LOG_PATH",
        order_log_path,
    )

    order_log_path.write_text(
        "".join(
            json.dumps(order, ensure_ascii=False) + "\n"
            for order in orders
        ),
        encoding="utf-8",
    )


def test_returns_none_when_position_is_not_held(
    tmp_path,
    monkeypatch,
):
    _save_orders(
        tmp_path,
        monkeypatch,
        [
            {
                "created_at": "2026-01-01T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
            {
                "created_at": "2026-01-10T09:00:00",
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 2600.0,
            },
        ],
    )

    result = order_manager.calculate_position_holding_days(
        "7203.T",
        current_time=datetime(2026, 2, 1, 9, 0, 0),
    )

    assert result is None


def test_calculates_holding_days_from_oldest_open_buy(
    tmp_path,
    monkeypatch,
):
    _save_orders(
        tmp_path,
        monkeypatch,
        [
            {
                "created_at": "2026-01-01T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
            {
                "created_at": "2026-01-11T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2550.0,
            },
        ],
    )

    result = order_manager.calculate_position_holding_days(
        "7203.T",
        current_time=datetime(2026, 1, 31, 9, 0, 0),
    )

    assert result == 30


def test_partial_sell_uses_oldest_remaining_lot(
    tmp_path,
    monkeypatch,
):
    _save_orders(
        tmp_path,
        monkeypatch,
        [
            {
                "created_at": "2026-01-01T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
            {
                "created_at": "2026-01-11T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2550.0,
            },
            {
                "created_at": "2026-01-20T09:00:00",
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 2600.0,
            },
        ],
    )

    result = order_manager.calculate_position_holding_days(
        "7203.T",
        current_time=datetime(2026, 1, 31, 9, 0, 0),
    )

    assert result == 20


def test_ignores_other_tickers_and_invalid_orders(
    tmp_path,
    monkeypatch,
):
    _save_orders(
        tmp_path,
        monkeypatch,
        [
            {
                "created_at": "invalid-date",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
            {
                "created_at": "2025-01-01T09:00:00",
                "ticker": "6758.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 3000.0,
            },
            {
                "created_at": "2026-01-21T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
        ],
    )

    result = order_manager.calculate_position_holding_days(
        "7203.T",
        current_time=datetime(2026, 1, 31, 9, 0, 0),
    )

    assert result == 10


def test_future_buy_time_returns_zero(
    tmp_path,
    monkeypatch,
):
    _save_orders(
        tmp_path,
        monkeypatch,
        [
            {
                "created_at": "2026-02-01T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
        ],
    )

    result = order_manager.calculate_position_holding_days(
        "7203.T",
        current_time=datetime(2026, 1, 31, 9, 0, 0),
    )

    assert result == 0
