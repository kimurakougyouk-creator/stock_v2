from execution import BrokerFactory, Order
from sbi_broker import SbiBroker


def _order() -> Order:
    return Order("7203.T", "BUY", 100, 1000.0, "2026-01-05T09:00:00", "unit-test")


def _assert_not_implemented(operation, expected_message: str) -> None:
    try:
        operation()
    except NotImplementedError as exc:
        assert expected_message in str(exc)
    else:
        raise AssertionError(f"{expected_message} should not be implemented yet")


def test_broker_factory_returns_sbi_broker(tmp_path):
    broker = BrokerFactory.create("sbi", log_dir=str(tmp_path))

    assert isinstance(broker, SbiBroker)


def test_sbi_broker_authentication_is_not_implemented(tmp_path):
    broker = SbiBroker(log_dir=str(tmp_path))

    _assert_not_implemented(broker.authenticate, "認証処理は未実装")


def test_sbi_broker_order_operations_are_not_implemented(tmp_path):
    broker = SbiBroker(log_dir=str(tmp_path))

    _assert_not_implemented(lambda: broker.submit_order(_order(), 200_000), "注文送信は未実装")
    _assert_not_implemented(lambda: broker.cancel_order("order-1"), "注文取消は未実装")


def test_sbi_broker_account_queries_are_not_implemented(tmp_path):
    broker = SbiBroker(log_dir=str(tmp_path))

    _assert_not_implemented(broker.get_balance, "残高取得は未実装")
    _assert_not_implemented(broker.get_positions, "保有銘柄取得は未実装")
