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
    next_order_id: int = 700
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


def test_multiple_orders_use_unique_sequential_ids(monkeypatch, tmp_path):
    session = FakeSession(next_order_id=700)

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order",
        _ready_guard,
    )

    broker = IbkrBrokerAdapter(
        enable_paper_order_transmission=True,
        fill_state_path=tmp_path / "fills.json",
    )
    assert broker.connect() is True

    results = [
        broker.place_order(OrderRequest("AAPL", OrderSide.BUY, 1)),
        broker.place_order(OrderRequest("MSFT", OrderSide.BUY, 1)),
        broker.place_order(OrderRequest("NVDA", OrderSide.BUY, 1)),
    ]

    assert [result.status for result in results] == [
        OrderStatus.ACCEPTED,
        OrderStatus.ACCEPTED,
        OrderStatus.ACCEPTED,
    ]
    assert [result.order_id for result in results] == ["700", "701", "702"]
    assert [entry[0] for entry in session.client.orders] == [700, 701, 702]
    assert session.next_order_id == 703


def test_rejected_not_sent_order_does_not_consume_order_id(
    monkeypatch,
    tmp_path,
):
    session = FakeSession(next_order_id=900)

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )

    broker = IbkrBrokerAdapter(
        enable_paper_order_transmission=False,
        fill_state_path=tmp_path / "fills.json",
    )
    assert broker.connect() is True

    result = broker.place_order(
        OrderRequest("AAPL", OrderSide.BUY, 1)
    )

    assert result.status is OrderStatus.REJECTED
    assert session.next_order_id == 900
    assert session.client.orders == []
