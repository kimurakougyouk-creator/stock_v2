from __future__ import annotations

from datetime import date
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


def test_calculate_daily_realized_pnl_uses_average_cost(
    tmp_path,
    monkeypatch,
) -> None:
    order_log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log)

    _write_orders(
        order_log,
        [
            {
                "created_at": "2026-07-27T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2000.0,
            },
            {
                "created_at": "2026-07-27T10:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2200.0,
            },
            {
                "created_at": "2026-07-28T11:00:00",
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 2000.0,
            },
        ],
    )

    result = order_manager.calculate_daily_realized_pnl(
        date(2026, 7, 28)
    )

    assert result == -10_000.0


def test_calculate_daily_realized_pnl_ignores_other_dates(
    tmp_path,
    monkeypatch,
) -> None:
    order_log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log)

    _write_orders(
        order_log,
        [
            {
                "created_at": "2026-07-26T09:00:00",
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2000.0,
            },
            {
                "created_at": "2026-07-27T11:00:00",
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 1900.0,
            },
        ],
    )

    result = order_manager.calculate_daily_realized_pnl(
        date(2026, 7, 28)
    )

    assert result == 0.0
