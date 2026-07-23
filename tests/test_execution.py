import json
from types import SimpleNamespace

from execution import DryRunBroker, Order, create_order_from_signal


def test_create_order_from_buy_signal():
    class SignalRow(SimpleNamespace):
        def __getitem__(self, key):
            return {"Buy": True, "Close": 1234.5}[key]

    order = create_order_from_signal("7203.T", SignalRow(name="2026-01-05"), 100, "unit-test")

    assert order.ticker == "7203.T"
    assert order.side == "BUY"
    assert order.quantity == 100
    assert order.price == 1234.5
    assert order.created_at == "2026-01-05"
    assert order.reason == "unit-test"


def test_dry_run_records_order_without_sending_to_broker(tmp_path):
    broker = DryRunBroker(
        order_file=tmp_path / "orders.json",
        log_file=tmp_path / "orders.log",
    )
    order = Order("7203.T", "BUY", 100, 1000.0, "2026-01-05T09:00:00", "buy_signal")

    assert broker.submit_order(order, available_cash=200_000)

    saved = json.loads((tmp_path / "orders.json").read_text(encoding="utf-8"))
    assert saved == [{
        "ticker": "7203.T",
        "side": "BUY",
        "quantity": 100,
        "price": 1000.0,
        "created_at": "2026-01-05T09:00:00",
        "reason": "buy_signal",
    }]


def test_dry_run_skips_duplicate_order(tmp_path):
    broker = DryRunBroker(
        order_file=tmp_path / "orders.json",
        log_file=tmp_path / "orders.log",
    )
    order = Order("7203.T", "BUY", 100, 1000.0, "2026-01-05T09:00:00", "buy_signal")

    assert broker.submit_order(order, available_cash=200_000)
    assert not broker.submit_order(order, available_cash=200_000)

    saved = json.loads((tmp_path / "orders.json").read_text(encoding="utf-8"))
    assert len(saved) == 1


def test_dry_run_rejects_invalid_order_and_logs_reason(tmp_path):
    broker = DryRunBroker(
        order_file=tmp_path / "orders.json",
        log_file=tmp_path / "orders.log",
    )
    order = Order("7203.T", "BUY", 200, 1000.0, "2026-01-05T09:00:00", "buy_signal")

    assert not broker.submit_order(order, available_cash=100_000)
    assert not (tmp_path / "orders.json").exists()
    assert "order amount exceeds available cash" in (tmp_path / "orders.log").read_text(encoding="utf-8")


def test_create_order_ignores_nan_buy_signal():
    class SignalRow(SimpleNamespace):
        def __getitem__(self, key):
            return {"Buy": float("nan"), "Close": 1234.5}[key]

    assert create_order_from_signal("7203.T", SignalRow(name="2026-01-05"), 100) is None


def _trade(**overrides):
    trade = {
        "buy_date": "2026-01-05T09:00:00",
        "sell_date": "2026-01-06T09:00:00",
        "buy_price": 1000.0,
        "sell_price": 1100.0,
        "shares": 100,
        "exit_reason": "take_profit",
        "capital": 210_000,
    }
    trade.update(overrides)
    return trade


def test_record_dry_run_orders_creates_buy_and_sell_orders(tmp_path):
    from execution import record_dry_run_orders

    broker = DryRunBroker(
        order_file=tmp_path / "orders.json",
        log_file=tmp_path / "orders.log",
    )

    recorded = record_dry_run_orders(
        "7203.T",
        {"trades": [_trade()]},
        broker,
        available_cash=200_000,
    )

    assert [(order.side, order.reason) for order in recorded] == [
        ("BUY", "buy_signal"),
        ("SELL", "take_profit"),
    ]

    saved = json.loads((tmp_path / "orders.json").read_text(encoding="utf-8"))
    assert [order["side"] for order in saved] == ["BUY", "SELL"]


def test_record_dry_run_orders_prevents_same_ticker_side_date_duplicates(tmp_path):
    from execution import record_dry_run_orders

    broker = DryRunBroker(
        order_file=tmp_path / "orders.json",
        log_file=tmp_path / "orders.log",
    )
    result = {"trades": [
        _trade(reason="first"),
        _trade(buy_price=1001.0, sell_price=1099.0, exit_reason="trailing_stop"),
    ]}

    recorded = record_dry_run_orders("7203.T", result, broker, available_cash=300_000)

    assert len(recorded) == 2
    saved = json.loads((tmp_path / "orders.json").read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert {order["side"] for order in saved} == {"BUY", "SELL"}


def test_record_dry_run_orders_safely_stops_when_dry_run_disabled(tmp_path):
    from execution import record_dry_run_orders

    broker = DryRunBroker(
        order_file=tmp_path / "orders.json",
        log_file=tmp_path / "orders.log",
    )

    recorded = record_dry_run_orders(
        "7203.T",
        {"trades": [_trade()]},
        broker,
        available_cash=200_000,
        dry_run=False,
    )

    assert recorded == []
    assert not (tmp_path / "orders.json").exists()
    assert "real order execution is not implemented" in (tmp_path / "orders.log").read_text(encoding="utf-8")
