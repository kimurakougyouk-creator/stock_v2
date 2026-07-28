from datetime import datetime, timedelta
import json

import order_manager


def _write_orders(tmp_path, monkeypatch, orders):
    order_path = tmp_path / "paper_orders.jsonl"
    order_path.write_text(
        "".join(
            json.dumps(order, ensure_ascii=False) + "\n"
            for order in orders
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", order_path)


def test_recent_sell_activates_repurchase_cooldown(
    tmp_path,
    monkeypatch,
):
    now = datetime(2026, 7, 28, 10, 0, 0)

    _write_orders(
        tmp_path,
        monkeypatch,
        [
            {
                "created_at": (
                    now - timedelta(minutes=20)
                ).isoformat(),
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 3000.0,
            }
        ],
    )

    remaining = (
        order_manager
        .calculate_repurchase_cooldown_remaining_minutes(
            "7203.T",
            60,
            current_time=now,
        )
    )

    assert remaining == 40


def test_expired_repurchase_cooldown_returns_zero(
    tmp_path,
    monkeypatch,
):
    now = datetime(2026, 7, 28, 10, 0, 0)

    _write_orders(
        tmp_path,
        monkeypatch,
        [
            {
                "created_at": (
                    now - timedelta(minutes=61)
                ).isoformat(),
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 3000.0,
            }
        ],
    )

    remaining = (
        order_manager
        .calculate_repurchase_cooldown_remaining_minutes(
            "7203.T",
            60,
            current_time=now,
        )
    )

    assert remaining == 0


def test_other_ticker_sell_does_not_activate_cooldown(
    tmp_path,
    monkeypatch,
):
    now = datetime(2026, 7, 28, 10, 0, 0)

    _write_orders(
        tmp_path,
        monkeypatch,
        [
            {
                "created_at": (
                    now - timedelta(minutes=10)
                ).isoformat(),
                "ticker": "6758.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 15000.0,
            }
        ],
    )

    remaining = (
        order_manager
        .calculate_repurchase_cooldown_remaining_minutes(
            "7203.T",
            60,
            current_time=now,
        )
    )

    assert remaining == 0


def test_zero_cooldown_disables_repurchase_limit(
    tmp_path,
    monkeypatch,
):
    now = datetime(2026, 7, 28, 10, 0, 0)

    _write_orders(
        tmp_path,
        monkeypatch,
        [
            {
                "created_at": now.isoformat(),
                "ticker": "7203.T",
                "side": "SELL",
                "shares": 100,
                "reference_price": 3000.0,
            }
        ],
    )

    remaining = (
        order_manager
        .calculate_repurchase_cooldown_remaining_minutes(
            "7203.T",
            0,
            current_time=now,
        )
    )

    assert remaining == 0
