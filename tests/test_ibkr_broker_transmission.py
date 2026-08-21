from dataclasses import dataclass, field

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_paper_order_guard import IbkrPaperOrderGuardResult
from ai_asset_platform.brokers.instruments import AssetClass, InstrumentSpec
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
    return IbkrPaperOrderGuardResult("READY", True, args[0], args[1], "ready")


def _connect_broker(monkeypatch, *, enable_transmission=False):
    session = FakeSession()
    monkeypatch.setattr("ai_asset_platform.brokers.ibkr.open_ibkr_paper_session", lambda config, **kwargs: session)
    monkeypatch.setattr("ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order", _ready_guard)
    broker = IbkrBrokerAdapter(enable_paper_order_transmission=enable_transmission)
    assert broker.connect() is True
    return broker, session


def test_broker_keeps_paper_order_unsent_by_default(monkeypatch):
    broker, session = _connect_broker(monkeypatch)
    result = broker.place_order(OrderRequest("AAPL", OrderSide.BUY, 1))
    assert result.status is OrderStatus.REJECTED
    assert result.order_id == "123"
    assert session.client.orders == []
    assert session.next_order_id == 123


def test_broker_can_send_paper_order_only_when_explicitly_enabled(monkeypatch):
    broker, session = _connect_broker(monkeypatch, enable_transmission=True)
    result = broker.place_order(OrderRequest("AAPL", OrderSide.BUY, 1))
    assert result.status is OrderStatus.ACCEPTED
    assert result.order_id == "123"
    assert len(session.client.orders) == 1
    assert session.client.orders[0][0] == 123
    assert session.next_order_id == 124


def test_broker_preserves_etf_instrument_to_contract(monkeypatch):
    broker, session = _connect_broker(monkeypatch, enable_transmission=True)
    instrument = InstrumentSpec("SPY", AssetClass.ETF, exchange="SMART", currency="USD")
    result = broker.place_order(OrderRequest("SPY", OrderSide.BUY, 1), instrument=instrument)
    assert result.status is OrderStatus.ACCEPTED
    assert len(session.client.orders) == 1
    _, contract, order = session.client.orders[0]
    assert contract.symbol == "SPY"
    assert contract.secType == "STK"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"
    assert order.transmit is True


def test_broker_does_not_consume_order_id_when_order_is_not_sent(monkeypatch):
    broker, session = _connect_broker(monkeypatch)
    broker.place_order(OrderRequest("AAPL", OrderSide.BUY, 1))
    broker.place_order(OrderRequest("AAPL", OrderSide.BUY, 1))
    assert session.next_order_id == 123
    assert session.client.orders == []
