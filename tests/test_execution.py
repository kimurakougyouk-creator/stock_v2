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
