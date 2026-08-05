import pytest

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
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
        lambda config: None,
    )

    broker = IbkrBrokerAdapter()

    assert broker.connect() is False
    assert broker.is_connected() is False


def test_ibkr_rejects_order_when_disconnected():
    broker = IbkrBrokerAdapter()

    result = broker.place_order(
        OrderRequest(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1,
        )
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

    with pytest.raises(
        RuntimeError,
        match="Live Tradingは安全ロック",
    ):
        broker.connect()


def test_ibkr_fill_is_disabled():
    broker = IbkrBrokerAdapter()

    order = OrderRequest(
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=1,
    )

    with pytest.raises(
        RuntimeError,
        match="実約定処理",
    ):
        broker.fill_order(
            order,
            200.0,
        )


def test_ibkr_disconnect_is_safe():
    broker = IbkrBrokerAdapter()

    broker.disconnect()

    assert broker.is_connected() is False


def test_ibkr_connect_uses_safe_paper_probe(monkeypatch):

    from ai_asset_platform.brokers.ibkr_session import (
        IbkrPaperSession,
    )

    class FakeClient:
        def __init__(self):
            self.connected = True

        def isConnected(self):
            return self.connected

        def disconnect(self):
            self.connected = False

    session = IbkrPaperSession(
        client=FakeClient(),
        next_order_id=123,
    )

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config: session,
    )

    broker = IbkrBrokerAdapter()

    assert broker.connect() is True
    assert broker.is_connected() is True


def test_ibkr_connect_stays_disconnected_when_probe_fails(
    monkeypatch,
):

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config: None,
    )

    broker = IbkrBrokerAdapter()

    assert broker.connect() is False
    assert broker.is_connected() is False


def test_ibkr_connected_order_is_prepared_but_not_sent(
    monkeypatch,
):

    from ai_asset_platform.brokers.ibkr_session import (
        IbkrPaperSession,
    )

    class FakeClient:
        def __init__(self):
            self.connected = True

        def isConnected(self):
            return self.connected

        def disconnect(self):
            self.connected = False

    session = IbkrPaperSession(
        client=FakeClient(),
        next_order_id=123,
    )

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config: session,
    )

    broker = IbkrBrokerAdapter()

    assert broker.connect() is True

    result = broker.place_order(
        OrderRequest(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1,
        )
    )

    assert result.order_id == "IBKR-PAPER-PREPARED"
    assert result.status is OrderStatus.REJECTED
    assert "準備まで完了" in result.message
    assert "送信していません" in result.message


def test_ibkr_connected_order_keeps_transmission_disabled(
    monkeypatch,
):
    from dataclasses import dataclass


    from ai_asset_platform.brokers.ibkr_session import (
        IbkrPaperSession,
    )

    class FakeClient:
        def __init__(self):
            self.connected = True

        def isConnected(self):
            return self.connected

        def disconnect(self):
            self.connected = False

    session = IbkrPaperSession(
        client=FakeClient(),
        next_order_id=123,
    )

    @dataclass
    class FakeOrder:
        transmit: bool = True

    @dataclass
    class FakePrepared:
        order: FakeOrder

    def unsafe_prepare(order, config):
        return FakePrepared(
            order=FakeOrder(transmit=True),
        )

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config: session,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.prepare_ibkr_paper_order",
        unsafe_prepare,
    )

    broker = IbkrBrokerAdapter()

    assert broker.connect() is True

    with pytest.raises(
        RuntimeError,
        match="transmitが有効",
    ):
        broker.place_order(
            OrderRequest(
                symbol="AAPL",
                side=OrderSide.BUY,
                quantity=1,
            )
        )
