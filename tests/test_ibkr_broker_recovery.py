from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderStatus


@dataclass
class FakeSession:
    connected: bool = True
    next_order_id: int = 123

    def disconnect(self) -> None:
        self.connected = False


def test_disconnect_then_reconnect_opens_new_session(monkeypatch, tmp_path):
    sessions = [FakeSession(next_order_id=123), FakeSession(next_order_id=200)]
    calls = []

    def fake_open(config, **kwargs):
        calls.append(kwargs)
        return sessions[len(calls) - 1]

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        fake_open,
    )

    broker = IbkrBrokerAdapter(fill_state_path=tmp_path / "fills.json")

    assert broker.connect() is True
    broker.disconnect()
    assert broker.is_connected() is False
    assert broker.connect() is True
    assert len(calls) == 2
    assert "order_status_handler" in calls[0]
    assert "order_status_handler" in calls[1]


def test_connection_loss_blocks_order_until_reconnect(monkeypatch, tmp_path):
    session = FakeSession()

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )

    broker = IbkrBrokerAdapter(fill_state_path=tmp_path / "fills.json")
    assert broker.connect() is True

    session.connected = False

    result = broker.place_order(
        OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)
    )

    assert result.status is OrderStatus.REJECTED
    assert result.order_id == "IBKR-NOT-CONNECTED"


def test_reconnect_keeps_fill_state_restored(monkeypatch, tmp_path):
    state_path = tmp_path / "fills.json"
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=3)

    first = IbkrBrokerAdapter(fill_state_path=state_path)
    first._fill_runtime.register_order(123, order)
    first._fill_runtime.process_order_status(
        123,
        "Submitted",
        2,
        1,
        100.0,
    )
    assert first.processed_filled(123) == 2.0

    sessions = [FakeSession(next_order_id=200), FakeSession(next_order_id=300)]
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

    restarted = IbkrBrokerAdapter(fill_state_path=state_path)
    assert restarted.processed_filled(123) == 2.0
    assert restarted.connect() is True
    restarted.disconnect()
    assert restarted.connect() is True
    assert restarted.processed_filled(123) == 2.0
