from __future__ import annotations

import json

import order_manager


def _write_orders(path, orders: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(order, ensure_ascii=False) + "\n"
            for order in orders
        ),
        encoding="utf-8",
    )


def test_calculate_consecutive_losses_returns_three(
    tmp_path,
    monkeypatch,
) -> None:
    order_log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log)

    _write_orders(
        order_log,
        [
            {
                "created_at": "2026-07-20T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2000.0,
            },
            {
                "created_at": "2026-07-20T15:00:00",
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 1900.0,
            },
            {
                "created_at": "2026-07-21T09:00:00",
                "ticker": "6758.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 3000.0,
            },
            {
                "created_at": "2026-07-21T15:00:00",
                "ticker": "6758.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 2900.0,
            },
            {
                "created_at": "2026-07-22T09:00:00",
                "ticker": "8306.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 1500.0,
            },
            {
                "created_at": "2026-07-22T15:00:00",
                "ticker": "8306.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 1400.0,
            },
        ],
    )

    assert order_manager.calculate_consecutive_losses() == 3


def test_profit_resets_consecutive_losses(
    tmp_path,
    monkeypatch,
) -> None:
    order_log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log)

    _write_orders(
        order_log,
        [
            {
                "created_at": "2026-07-20T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2000.0,
            },
            {
                "created_at": "2026-07-20T15:00:00",
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 1900.0,
            },
            {
                "created_at": "2026-07-21T09:00:00",
                "ticker": "6758.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 3000.0,
            },
            {
                "created_at": "2026-07-21T15:00:00",
                "ticker": "6758.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 3200.0,
            },
            {
                "created_at": "2026-07-22T09:00:00",
                "ticker": "8306.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 1500.0,
            },
            {
                "created_at": "2026-07-22T15:00:00",
                "ticker": "8306.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 1400.0,
            },
        ],
    )

    assert order_manager.calculate_consecutive_losses() == 1
