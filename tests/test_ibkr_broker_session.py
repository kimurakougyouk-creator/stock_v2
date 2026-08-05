from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter


@dataclass
class FakeSession:
    connected: bool = True
    disconnected: bool = False
    next_order_id: int = 123

    def disconnect(self) -> None:
        self.disconnected = True
        self.connected = False


def test_broker_uses_persistent_paper_session(monkeypatch):
    session = FakeSession()

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config: session,
    )

    broker = IbkrBrokerAdapter()

    assert broker.connect() is True
    assert broker.is_connected() is True


def test_broker_stays_disconnected_when_session_open_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config: None,
    )

    broker = IbkrBrokerAdapter()

    assert broker.connect() is False
    assert broker.is_connected() is False


def test_broker_disconnect_closes_session(monkeypatch):
    session = FakeSession()

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config: session,
    )

    broker = IbkrBrokerAdapter()

    assert broker.connect() is True

    broker.disconnect()

    assert session.disconnected is True
    assert broker.is_connected() is False


def test_repeated_connect_reuses_existing_session(monkeypatch):
    calls = 0
    session = FakeSession()

    def fake_open(config):
        nonlocal calls
        calls += 1
        return session

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        fake_open,
    )

    broker = IbkrBrokerAdapter()

    assert broker.connect() is True
    assert broker.connect() is True
    assert calls == 1
