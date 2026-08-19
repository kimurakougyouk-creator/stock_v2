from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.ibkr_paper_order_guard import (
    IbkrPaperOrderGuardResult,
)
from ai_asset_platform.brokers.ibkr_paper_transmitter import (
    transmit_ibkr_paper_order,
)
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide


class FakeClient:
    def __init__(self):
        self.calls = []

    def placeOrder(self, order_id, contract, order):  # noqa: N802
        self.calls.append((order_id, contract, order))


def ready_guard(symbol="AAPL", quantity=1):
    return IbkrPaperOrderGuardResult(
        status="READY",
        allowed=True,
        symbol=symbol,
        quantity=quantity,
        message="ready",
    )


def test_transmission_is_disabled_by_default():
    client = FakeClient()
    request = OrderRequest("AAPL", OrderSide.BUY, 1)

    result = transmit_ibkr_paper_order(
        request,
        create_ibkr_paper_config(),
        client=client,
        next_order_id=100,
        guard=ready_guard(),
    )

    assert result.status == "READY_NOT_SENT"
    assert result.sent is False
    assert result.order_id == 100
    assert client.calls == []


def test_guard_blocks_transmission():
    client = FakeClient()
    request = OrderRequest("AAPL", OrderSide.BUY, 1)
    guard = IbkrPaperOrderGuardResult(
        status="WAITING",
        allowed=False,
        symbol="AAPL",
        quantity=1,
        message="waiting",
    )

    result = transmit_ibkr_paper_order(
        request,
        create_ibkr_paper_config(),
        client=client,
        next_order_id=100,
        enable_transmission=True,
        guard=guard,
    )

    assert result.sent is False
    assert client.calls == []


def test_missing_next_order_id_blocks_transmission():
    client = FakeClient()
    request = OrderRequest("AAPL", OrderSide.BUY, 1)

    result = transmit_ibkr_paper_order(
        request,
        create_ibkr_paper_config(),
        client=client,
        next_order_id=None,
        enable_transmission=True,
        guard=ready_guard(),
    )

    assert result.status == "WAITING"
    assert result.sent is False
    assert client.calls == []


def test_live_configuration_is_blocked():
    client = FakeClient()
    request = OrderRequest("AAPL", OrderSide.BUY, 1)
    config = IbkrConnectionConfig(
        host="127.0.0.1",
        port=7496,
        client_id=0,
        paper_trading=False,
        allow_live_trading=True,
    )

    result = transmit_ibkr_paper_order(
        request,
        config,
        client=client,
        next_order_id=100,
        enable_transmission=True,
        guard=ready_guard(),
    )

    assert result.status == "BLOCKED"
    assert result.sent is False
    assert client.calls == []


def test_default_guard_uses_tws_port_when_config_is_tws(monkeypatch):
    """明示的なTWS(7497)設定ならuse_gateway=Falseで自動ガードすること。"""
    import ai_asset_platform.brokers.ibkr_paper_transmitter as transmitter

    seen_kwargs = []

    def fake_validate(symbol, quantity, **kwargs):
        seen_kwargs.append(kwargs)
        return ready_guard(symbol, quantity)

    monkeypatch.setattr(
        transmitter,
        "validate_ibkr_paper_test_order",
        fake_validate,
    )

    client = FakeClient()
    request = OrderRequest("AAPL", OrderSide.BUY, 1)

    result = transmit_ibkr_paper_order(
        request,
        create_ibkr_paper_config(use_gateway=False),
        client=client,
        next_order_id=100,
    )

    assert seen_kwargs == [{"use_gateway": False}]
    assert result.status == "READY_NOT_SENT"
    assert client.calls == []


def test_default_guard_uses_gateway_port_when_config_is_gateway(monkeypatch):
    """guard未指定時、Gateway(4002)設定ならuse_gateway=Trueが伝播すること。

    IbkrBrokerAdapter.place_order()はguardを明示せずこの関数を呼ぶため、
    Gateway接続時にTWS(7497)を誤って確認しないことが送信前の安全確認上重要。
    """
    import ai_asset_platform.brokers.ibkr_paper_transmitter as transmitter

    seen_kwargs = []

    def fake_validate(symbol, quantity, **kwargs):
        seen_kwargs.append(kwargs)
        return ready_guard(symbol, quantity)

    monkeypatch.setattr(
        transmitter,
        "validate_ibkr_paper_test_order",
        fake_validate,
    )

    client = FakeClient()
    request = OrderRequest("AAPL", OrderSide.BUY, 1)

    result = transmit_ibkr_paper_order(
        request,
        create_ibkr_paper_config(use_gateway=True),
        client=client,
        next_order_id=100,
    )

    assert seen_kwargs == [{"use_gateway": True}]
    assert result.status == "READY_NOT_SENT"
    assert client.calls == []


def test_explicit_enable_sends_one_paper_order():
    client = FakeClient()
    request = OrderRequest("AAPL", OrderSide.BUY, 1)

    result = transmit_ibkr_paper_order(
        request,
        create_ibkr_paper_config(),
        client=client,
        next_order_id=321,
        enable_transmission=True,
        guard=ready_guard(),
    )

    assert result.status == "SENT"
    assert result.sent is True
    assert result.order_id == 321
    assert len(client.calls) == 1
    order_id, contract, order = client.calls[0]
    assert order_id == 321
    assert contract.symbol == "AAPL"
    assert order.action == "BUY"
    assert order.totalQuantity == 1
    assert order.orderType == "MKT"
    assert order.transmit is True
