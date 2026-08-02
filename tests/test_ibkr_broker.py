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


def test_ibkr_connect_does_not_fake_connection():
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
