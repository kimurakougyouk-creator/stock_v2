import json

from auto_trading_engine import run_dry_run_trading_cycle
from stability import FatalOperationalError


def _result():
    return {
        "trades": [
            {
                "buy_date": "2026-01-05T09:00:00",
                "sell_date": "2026-01-06T09:00:00",
                "buy_price": 1000.0,
                "sell_price": 1100.0,
                "shares": 100,
                "exit_reason": "take_profit",
                "capital": 210_000,
            }
        ]
    }


def test_trading_cycle_records_buy_and_sell_orders_through_factory(tmp_path):
    order_file = tmp_path / "orders.json"

    orders = run_dry_run_trading_cycle(
        "7203.T",
        _result(),
        broker_mode="dry_run",
        order_file=order_file,
        available_cash=200_000,
        dry_run=True,
    )

    assert [(order.side, order.reason) for order in orders] == [
        ("BUY", "buy_signal"),
        ("SELL", "take_profit"),
    ]
    saved = json.loads(order_file.read_text(encoding="utf-8"))
    assert [order["side"] for order in saved] == ["BUY", "SELL"]


def test_trading_cycle_prevents_duplicate_same_ticker_side_date_orders(tmp_path):
    order_file = tmp_path / "orders.json"

    first = run_dry_run_trading_cycle(
        "7203.T",
        _result(),
        broker_mode="dry_run",
        order_file=order_file,
        available_cash=200_000,
        dry_run=True,
    )
    second = run_dry_run_trading_cycle(
        "7203.T",
        _result(),
        broker_mode="dry_run",
        order_file=order_file,
        available_cash=200_000,
        dry_run=True,
    )

    assert len(first) == 2
    assert second == []
    saved = json.loads(order_file.read_text(encoding="utf-8"))
    assert len(saved) == 2


def test_trading_cycle_safely_stops_when_dry_run_disabled(tmp_path):
    order_file = tmp_path / "orders.json"

    try:
        run_dry_run_trading_cycle(
            "7203.T",
            _result(),
            broker_mode="dry_run",
            order_file=order_file,
            available_cash=200_000,
            dry_run=False,
        )
    except FatalOperationalError as exc:
        assert "DryRunのみ実行できます" in str(exc)
    else:
        raise AssertionError("dry_run=False should stop safely")

    assert not order_file.exists()


def test_trading_cycle_does_not_create_sbi_broker_for_real_execution(tmp_path):
    order_file = tmp_path / "orders.json"

    try:
        run_dry_run_trading_cycle(
            "7203.T",
            _result(),
            broker_mode="sbi",
            order_file=order_file,
            available_cash=200_000,
            dry_run=True,
        )
    except FatalOperationalError as exc:
        assert "DryRunのみ実行できます" in str(exc)
    else:
        raise AssertionError("broker_mode=sbi should stop safely in trading cycle")

    assert not order_file.exists()
