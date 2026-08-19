from ai_asset_platform.account import Account
from ai_asset_platform.brokers.ibkr import IbkrAsyncOrderResult, IbkrBrokerAdapter
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.execution.service import ExecutionService


def _result(**overrides):
    values = dict(
        order_intent_id="signal-1",
        status="TERMINAL",
        sent=True,
        order_id=7,
        reached_terminal=True,
        timed_out=False,
        last_known_status="Filled",
        filled_quantity=1.0,
        avg_fill_price=100.0,
        message="filled",
    )
    values.update(overrides)
    return IbkrAsyncOrderResult(**values)


def _broker(result):
    broker = IbkrBrokerAdapter.__new__(IbkrBrokerAdapter)
    broker.is_connected = lambda: True
    calls = []

    def place_order_and_await_fill(order, **kwargs):
        calls.append((order, kwargs))
        return result

    broker.place_order_and_await_fill = place_order_and_await_fill
    return broker, calls


def test_ibkr_filled_buy_updates_account_once():
    broker, calls = _broker(_result())
    account = Account(initial_cash=1_000.0)
    service = ExecutionService(broker=broker, account=account)
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)

    result = service.execute_ibkr_paper_order(
        order,
        order_intent_id="signal-1",
        timeout_seconds=5.0,
        poll_interval_seconds=0.1,
    )

    assert result.last_known_status == "Filled"
    assert len(calls) == 1
    assert calls[0][1]["order_intent_id"] == "signal-1"
    assert account.cash == 900.0
    position = account.portfolio.get_position("AAPL")
    assert position is not None
    assert position.quantity == 1
    assert position.average_price == 100.0


def test_ibkr_timeout_does_not_update_account_or_resend():
    broker, calls = _broker(
        _result(
            status="TIMEOUT",
            reached_terminal=False,
            timed_out=True,
            last_known_status=None,
            filled_quantity=0.0,
            avg_fill_price=None,
        )
    )
    account = Account(initial_cash=1_000.0)
    service = ExecutionService(broker=broker, account=account)
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)

    result = service.execute_ibkr_paper_order(order, order_intent_id="signal-2")

    assert result.timed_out is True
    assert len(calls) == 1
    assert account.cash == 1_000.0
    assert account.portfolio.get_position("AAPL") is None


def test_ibkr_rejected_or_unknown_does_not_update_account():
    broker, calls = _broker(
        _result(
            status="REJECTED",
            sent=False,
            order_id=None,
            reached_terminal=False,
            last_known_status=None,
            filled_quantity=0.0,
            avg_fill_price=None,
        )
    )
    account = Account(initial_cash=1_000.0)
    service = ExecutionService(broker=broker, account=account)
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)

    service.execute_ibkr_paper_order(order, order_intent_id="signal-3")

    assert len(calls) == 1
    assert account.cash == 1_000.0
    assert account.portfolio.get_position("AAPL") is None


def test_ibkr_cancelled_terminal_does_not_update_account():
    broker, _ = _broker(
        _result(
            status="TERMINAL",
            last_known_status="Cancelled",
            filled_quantity=0.0,
            avg_fill_price=None,
        )
    )
    account = Account(initial_cash=1_000.0)
    service = ExecutionService(broker=broker, account=account)
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)

    service.execute_ibkr_paper_order(order, order_intent_id="signal-4")

    assert account.cash == 1_000.0
    assert account.portfolio.get_position("AAPL") is None


def test_ibkr_fractional_fill_is_not_silently_truncated():
    broker, _ = _broker(_result(filled_quantity=0.5))
    account = Account(initial_cash=1_000.0)
    service = ExecutionService(broker=broker, account=account)
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)

    try:
        service.execute_ibkr_paper_order(order, order_intent_id="signal-5")
    except RuntimeError as error:
        assert "端数株" in str(error)
    else:
        raise AssertionError("端数株を整数へ黙って変換しました")

    assert account.cash == 1_000.0


def test_ibkr_path_requires_connected_ibkr_adapter():
    broker, _ = _broker(_result())
    broker.is_connected = lambda: False
    service = ExecutionService(broker=broker, account=Account(initial_cash=1_000.0))
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)

    try:
        service.execute_ibkr_paper_order(order, order_intent_id="signal-6")
    except RuntimeError as error:
        assert "接続" in str(error)
    else:
        raise AssertionError("未接続IBKR注文を拒否しませんでした")
