import pytest

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
)
from ai_asset_platform.brokers.ibkr_paper_order_guard import (
    IbkrPaperOrderGuardResult,
)
from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderSide,
    OrderStatus,
)


def test_ibkr_name():
    broker = IbkrBrokerAdapter()
    assert broker.name == "IBKR"


def test_ibkr_starts_disconnected():
    broker = IbkrBrokerAdapter()
    assert broker.is_connected() is False


def test_ibkr_connect_does_not_fake_connection(monkeypatch):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: None,
    )
    broker = IbkrBrokerAdapter()
    assert broker.connect() is False
    assert broker.is_connected() is False


def test_ibkr_rejects_order_when_disconnected():
    broker = IbkrBrokerAdapter()
    result = broker.place_order(
        OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)
    )
    assert result.status is OrderStatus.REJECTED
    assert "接続されていない" in result.message


def test_ibkr_live_locked_config_stops_connect():
    broker = IbkrBrokerAdapter(
        IbkrConnectionConfig(
            port=7496,
            paper_trading=False,
            allow_live_trading=False,
        )
    )
    with pytest.raises(RuntimeError, match="Live Tradingは安全ロック"):
        broker.connect()


def test_ibkr_fill_is_disabled():
    broker = IbkrBrokerAdapter()
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)
    with pytest.raises(RuntimeError, match="実約定処理"):
        broker.fill_order(order, 200.0)


def test_ibkr_disconnect_is_safe():
    broker = IbkrBrokerAdapter()
    broker.disconnect()
    assert broker.is_connected() is False


def _paper_session():
    from ai_asset_platform.brokers.ibkr_session import IbkrPaperSession

    class FakeClient:
        def __init__(self):
            self.connected = True
            self.calls = []

        def isConnected(self):  # noqa: N802
            return self.connected

        def disconnect(self):
            self.connected = False

        def placeOrder(self, order_id, contract, order):  # noqa: N802
            self.calls.append((order_id, contract, order))

    return IbkrPaperSession(client=FakeClient(), next_order_id=123)


def _ready_guard(symbol="AAPL", quantity=1):
    return IbkrPaperOrderGuardResult(
        status="READY",
        allowed=True,
        symbol=symbol,
        quantity=quantity,
        message="ready",
    )


def test_ibkr_connect_uses_safe_paper_probe(monkeypatch):
    session = _paper_session()
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )
    broker = IbkrBrokerAdapter()
    assert broker.connect() is True
    assert broker.is_connected() is True


def test_ibkr_connect_stays_disconnected_when_probe_fails(monkeypatch):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: None,
    )
    broker = IbkrBrokerAdapter()
    assert broker.connect() is False
    assert broker.is_connected() is False


def test_ibkr_connected_order_is_ready_but_not_sent_by_default(monkeypatch):
    session = _paper_session()
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order",
        lambda symbol, quantity: _ready_guard(symbol, quantity),
    )

    broker = IbkrBrokerAdapter()
    assert broker.connect() is True

    result = broker.place_order(
        OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)
    )

    assert result.order_id == "123"
    assert result.status is OrderStatus.REJECTED
    assert "安全ロックにより未送信" in result.message
    assert session.client.calls == []
    assert session.next_order_id == 123


def test_ibkr_connected_order_keeps_transmission_disabled(monkeypatch):
    session = _paper_session()
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order",
        lambda symbol, quantity: _ready_guard(symbol, quantity),
    )

    broker = IbkrBrokerAdapter()
    assert broker.connect() is True

    result = broker.place_order(
        OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)
    )

    assert result.status is OrderStatus.REJECTED
    assert session.client.calls == []
