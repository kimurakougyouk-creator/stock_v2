from __future__ import annotations

import json

import pytest

import order_manager


def _write_orders(path, orders: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(order, ensure_ascii=False) + "\n"
            for order in orders
        ),
        encoding="utf-8",
    )


def test_calculate_available_cash_without_orders(
    tmp_path,
    monkeypatch,
) -> None:
    order_log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log)

    assert order_manager.calculate_available_cash(
        1_000_000
    ) == 1_000_000


def test_calculate_available_cash_after_buy(
    tmp_path,
    monkeypatch,
) -> None:
    order_log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log)

    _write_orders(
        order_log,
        [
            {
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
        ],
    )

    assert order_manager.calculate_available_cash(
        1_000_000
    ) == 750_000


def test_calculate_available_cash_after_buy_and_sell(
    tmp_path,
    monkeypatch,
) -> None:
    order_log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log)

    _write_orders(
        order_log,
        [
            {
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 100,
                "reference_price": 2500.0,
            },
            {
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 50,
                "reference_price": 2700.0,
            },
        ],
    )

    assert order_manager.calculate_available_cash(
        1_000_000
    ) == 885_000


def test_calculate_available_cash_never_returns_negative(
    tmp_path,
    monkeypatch,
) -> None:
    order_log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log)

    _write_orders(
        order_log,
        [
            {
                "ticker": "7203.T",
                "side": "BUY",
                "shares": 1000,
                "reference_price": 2500.0,
            },
        ],
    )

    assert order_manager.calculate_available_cash(
        1_000_000
    ) == 0.0


def test_calculate_available_cash_rejects_negative_capital(
    tmp_path,
    monkeypatch,
) -> None:
    order_log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_log)

    with pytest.raises(ValueError):
        order_manager.calculate_available_cash(-1)
