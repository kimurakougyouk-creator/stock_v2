from dataclasses import dataclass, field

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_paper_order_guard import IbkrPaperOrderGuardResult
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderStatus


@dataclass
class FakeClient:
    orders: list[tuple] = field(default_factory=list)

    def placeOrder(self, order_id, contract, order):  # noqa: N802
        self.orders.append((order_id, contract, order))

    def isConnected(self):  # noqa: N802
        return True

    def disconnect(self):
        return None


@dataclass
class FakeSession:
    client: FakeClient = field(default_factory=FakeClient)
    next_order_id: int = 123
    connected: bool = True

    def disconnect(self):
        self.connected = False


def _ready_guard(*args, **kwargs):
    return IbkrPaperOrderGuardResult(
        status="READY",
        allowed=True,
        symbol=args[0],
        quantity=args[1],
        message="ready",
    )


def test_reconnect_uses_new_server_order_id(monkeypatch, tmp_path):
    sessions = [
        FakeSession(next_order_id=123),
        FakeSession(next_order_id=500),
    ]
    index = 0

    def fake_open(config, **kwargs):
        nonlocal index
        session = sessions[index]
        index += 1
        return session

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        fake_open,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order",
        _ready_guard,
    )

    broker = IbkrBrokerAdapter(
        enable_paper_order_transmission=True,
        fill_state_path=tmp_path / "fills.json",
    )
    order = OrderRequest("AAPL", OrderSide.BUY, 1)

    assert broker.connect() is True
    first = broker.place_order(order)
    assert first.status is OrderStatus.ACCEPTED
    assert first.order_id == "123"

    broker.disconnect()
    assert broker.connect() is True

    second = broker.place_order(order)
    assert second.status is OrderStatus.ACCEPTED
    assert second.order_id == "500"
    assert sessions[0].client.orders[0][0] == 123
    assert sessions[1].client.orders[0][0] == 500


def test_failed_reconnect_keeps_orders_blocked(monkeypatch, tmp_path):
    sessions = [FakeSession(next_order_id=123), None]
    index = 0

    def fake_open(config, **kwargs):
        nonlocal index
        session = sessions[index]
        index += 1
        return session

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        fake_open,
    )

    broker = IbkrBrokerAdapter(fill_state_path=tmp_path / "fills.json")
    assert broker.connect() is True
    broker.disconnect()
    assert broker.connect() is False

    result = broker.place_order(
        OrderRequest("AAPL", OrderSide.BUY, 1)
    )
    assert result.status is OrderStatus.REJECTED
    assert result.order_id == "IBKR-NOT-CONNECTED"
