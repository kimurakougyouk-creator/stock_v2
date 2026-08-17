from dataclasses import dataclass, field

from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.ibkr_first_paper_test import (
    REQUIRED_QUANTITY,
    REQUIRED_SIDE,
    REQUIRED_SYMBOL,
    IbkrFirstPaperTestGateway,
    validate_first_paper_test_conditions,
)
from ai_asset_platform.brokers.ibkr_paper_order_guard import (
    IbkrPaperOrderGuardResult,
)
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderStatus


@dataclass
class FakeClient:
    calls: list = field(default_factory=list)

    def placeOrder(self, order_id, contract, order):  # noqa: N802
        self.calls.append((order_id, contract, order))

    def isConnected(self):  # noqa: N802
        return True

    def disconnect(self):
        return None


@dataclass
class FakeSession:
    client: FakeClient = field(default_factory=FakeClient)
    next_order_id: int = 555
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


def _connected_gateway(monkeypatch, tmp_path, *, enable_transmission):
    session = FakeSession()
    captured = {}

    def fake_open(config, *, order_status_handler=None):
        captured["handler"] = order_status_handler
        return session

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        fake_open,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order",
        _ready_guard,
    )

    gateway = IbkrFirstPaperTestGateway(
        enable_transmission=enable_transmission,
        fill_state_path=tmp_path / "fills.json",
    )
    assert gateway.connect() is True
    return gateway, session, captured


def _gateway_config():
    return create_ibkr_paper_config(use_gateway=True)


def _base_order():
    return OrderRequest(
        symbol=REQUIRED_SYMBOL,
        side=REQUIRED_SIDE,
        quantity=REQUIRED_QUANTITY,
    )


# --- 1. Gateway 4002 / Paper / Live固定の確認 (要件1-3) ---


def test_gateway_is_fixed_to_ib_gateway_paper_endpoint():
    gateway = IbkrFirstPaperTestGateway()
    assert gateway.config.host == "127.0.0.1"
    assert gateway.config.port == 4002
    assert gateway.config.paper_trading is True
    assert gateway.config.allow_live_trading is False


def test_connect_fails_safely_when_probe_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: None,
    )
    gateway = IbkrFirstPaperTestGateway(fill_state_path=tmp_path / "fills.json")
    assert gateway.connect() is False
    assert gateway.is_connected() is False


# --- 要件7-9: 初期送信禁止 / 明示許可のみ送信 / 1回の実行で最大1回 ---


def test_transmission_disabled_by_default_calls_place_order_zero_times(
    monkeypatch, tmp_path
):
    gateway, session, _ = _connected_gateway(
        monkeypatch, tmp_path, enable_transmission=False
    )

    result = gateway.place_first_test_order()

    assert result.sent is False
    assert session.client.calls == []


def test_explicit_enable_calls_place_order_exactly_once(monkeypatch, tmp_path):
    gateway, session, _ = _connected_gateway(
        monkeypatch, tmp_path, enable_transmission=True
    )

    result = gateway.place_first_test_order()

    assert result.sent is True
    assert result.status == OrderStatus.ACCEPTED.value
    assert result.order_id == "555"
    assert len(session.client.calls) == 1

    order_id, contract, order = session.client.calls[0]
    assert order_id == 555
    assert contract.symbol == "AAPL"
    assert order.action == "BUY"
    assert order.totalQuantity == 1
    assert order.transmit is True


def test_second_attempt_is_blocked_and_place_order_stays_at_most_once(
    monkeypatch, tmp_path
):
    gateway, session, _ = _connected_gateway(
        monkeypatch, tmp_path, enable_transmission=True
    )

    first = gateway.place_first_test_order()
    second = gateway.place_first_test_order()
    third = gateway.place_first_test_order()

    assert first.sent is True
    assert second.sent is False
    assert second.status == "BLOCKED_ALREADY_ATTEMPTED"
    assert third.sent is False
    assert third.status == "BLOCKED_ALREADY_ATTEMPTED"
    assert len(session.client.calls) == 1


def test_second_attempt_is_blocked_even_when_transmission_disabled(
    monkeypatch, tmp_path
):
    gateway, session, _ = _connected_gateway(
        monkeypatch, tmp_path, enable_transmission=False
    )

    first = gateway.place_first_test_order()
    second = gateway.place_first_test_order()

    assert first.sent is False
    assert second.status == "BLOCKED_ALREADY_ATTEMPTED"
    assert session.client.calls == []


# --- 要件10-11: nextValidId取得 / orderStatus確認 ---


def test_order_id_comes_from_real_ibkr_next_valid_id(monkeypatch, tmp_path):
    session = FakeSession(next_order_id=987)
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order",
        _ready_guard,
    )

    gateway = IbkrFirstPaperTestGateway(
        enable_transmission=True,
        fill_state_path=tmp_path / "fills.json",
    )
    assert gateway.connect() is True

    result = gateway.place_first_test_order()

    assert result.order_id == "987"
    assert session.client.calls[0][0] == 987


def test_order_status_snapshot_reflects_real_order_status_callback(
    monkeypatch, tmp_path
):
    gateway, session, captured = _connected_gateway(
        monkeypatch, tmp_path, enable_transmission=True
    )

    result = gateway.place_first_test_order()
    assert result.sent is True
    order_id = int(result.order_id)

    assert gateway.order_status_snapshot(order_id) == 0.0

    # IBKRからの実orderStatusコールバックを模擬する
    captured["handler"](order_id, "Filled", 1.0, 0.0, 150.25)

    assert gateway.order_status_snapshot(order_id) == 1.0


# --- 要件12 / AAPL・BUY・数量1固定の検証 ---


def test_validate_allows_exact_required_order():
    assert (
        validate_first_paper_test_conditions(_gateway_config(), _base_order())
        is None
    )


def test_validate_rejects_symbol_other_than_aapl():
    order = OrderRequest(symbol="MSFT", side=OrderSide.BUY, quantity=1)
    blocked = validate_first_paper_test_conditions(_gateway_config(), order)

    assert blocked is not None
    assert blocked.status == "BLOCKED_SYMBOL"
    assert blocked.sent is False


def test_validate_rejects_side_other_than_buy():
    order = OrderRequest(symbol="AAPL", side=OrderSide.SELL, quantity=1)
    blocked = validate_first_paper_test_conditions(_gateway_config(), order)

    assert blocked is not None
    assert blocked.status == "BLOCKED_SIDE"
    assert blocked.sent is False


def test_validate_rejects_quantity_other_than_one():
    order = OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=2)
    blocked = validate_first_paper_test_conditions(_gateway_config(), order)

    assert blocked is not None
    assert blocked.status == "BLOCKED_QUANTITY"
    assert blocked.sent is False


def test_validate_rejects_live_configuration():
    config = IbkrConnectionConfig(
        host="127.0.0.1",
        port=4002,
        paper_trading=False,
        allow_live_trading=True,
    )
    blocked = validate_first_paper_test_conditions(config, _base_order())

    assert blocked is not None
    assert blocked.status == "BLOCKED_LIVE_CONFIG"
    assert blocked.sent is False


def test_validate_rejects_port_other_than_gateway_4002():
    config = IbkrConnectionConfig(
        host="127.0.0.1",
        port=7497,
        paper_trading=True,
        allow_live_trading=False,
    )
    blocked = validate_first_paper_test_conditions(config, _base_order())

    assert blocked is not None
    assert blocked.status == "BLOCKED_WRONG_ENDPOINT"
    assert blocked.sent is False
