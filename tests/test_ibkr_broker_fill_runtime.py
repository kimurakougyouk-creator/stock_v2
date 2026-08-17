from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_session import IbkrPaperSession
from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderSide,
    OrderStatus,
)


class FakeClient:
    def __init__(self) -> None:
        self.connected = True

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False


@dataclass
class FakeTransmitResult:
    sent: bool
    order_id: int | None
    message: str


def test_connect_wires_order_status_handler(monkeypatch, tmp_path):
    captured = {}
    session = IbkrPaperSession(
        client=FakeClient(),
        next_order_id=123,
    )

    def fake_open(config, *, order_status_handler=None):
        captured["handler"] = order_status_handler
        return session

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        fake_open,
    )

    broker = IbkrBrokerAdapter(
        fill_state_path=tmp_path / "fill_state.json",
    )

    assert broker.connect() is True
    assert callable(captured["handler"])


def test_sent_order_is_registered_for_fill_runtime(
    monkeypatch,
    tmp_path,
):
    captured = {}
    fills = []
    session = IbkrPaperSession(
        client=FakeClient(),
        next_order_id=123,
    )

    def fake_open(config, *, order_status_handler=None):
        captured["handler"] = order_status_handler
        return session

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        fake_open,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.transmit_ibkr_paper_order",
        lambda *args, **kwargs: FakeTransmitResult(
            sent=True,
            order_id=123,
            message="paper sent",
        ),
    )

    broker = IbkrBrokerAdapter(
        enable_paper_order_transmission=True,
        fill_state_path=tmp_path / "fill_state.json",
        on_fill=fills.append,
    )
    assert broker.connect() is True

    request = OrderRequest(
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=1,
    )
    result = broker.place_order(request)

    assert result.status is OrderStatus.ACCEPTED
    assert result.order_id == "123"

    captured["handler"](
        123,
        "Filled",
        1.0,
        0.0,
        200.0,
    )

    assert broker.processed_filled(123) == 1.0
    assert len(fills) == 1
    assert fills[0].quantity == 1
    assert fills[0].fill_price == 200.0


def test_unknown_order_status_is_ignored_safely(
    monkeypatch,
    tmp_path,
):
    captured = {}
    session = IbkrPaperSession(
        client=FakeClient(),
        next_order_id=123,
    )

    def fake_open(config, *, order_status_handler=None):
        captured["handler"] = order_status_handler
        return session

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        fake_open,
    )

    broker = IbkrBrokerAdapter(
        fill_state_path=tmp_path / "fill_state.json",
    )
    assert broker.connect() is True

    assert captured["handler"](
        999,
        "Filled",
        1.0,
        0.0,
        200.0,
    ) is None
    assert broker.processed_filled(999) == 0.0
