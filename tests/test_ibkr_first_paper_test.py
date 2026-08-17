import threading
from dataclasses import dataclass, field

from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.ibkr_first_paper_test import (
    REQUIRED_CLIENT_ID,
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


def _connected_gateway(
    monkeypatch,
    tmp_path,
    *,
    enable_transmission,
    session=None,
    lock_path=None,
    fill_state_name="fills.json",
):
    session = session or FakeSession()
    captured = {}

    def fake_open(config, *, order_status_handler=None, **kwargs):
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
        fill_state_path=tmp_path / fill_state_name,
        # 実運用ロック(data/ibkr_first_paper_test_send.lock)を汚さないよう、
        # テストでは必ず一時ディレクトリ配下のロックパスを使う。
        lock_path=lock_path or (tmp_path / "send.lock"),
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
    assert gateway.config.client_id == REQUIRED_CLIENT_ID


def test_client_id_is_dedicated_and_differs_from_generic_default():
    """汎用システムの既定client_id(0)と衝突しないことを確認する。"""
    gateway = IbkrFirstPaperTestGateway()
    assert gateway.config.client_id != 0


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


# --- プロセスを跨いだ永続one-shot送信ロック ---


def test_dry_run_does_not_create_persistent_lock_file(monkeypatch, tmp_path):
    lock_path = tmp_path / "send.lock"
    gateway, session, _ = _connected_gateway(
        monkeypatch,
        tmp_path,
        enable_transmission=False,
        lock_path=lock_path,
    )

    result = gateway.place_first_test_order()

    assert result.sent is False
    assert session.client.calls == []
    assert lock_path.exists() is False


def test_first_transmission_creates_lock_and_second_process_is_blocked(
    monkeypatch, tmp_path
):
    """1回目の送信試行だけが永続ロックを作成し許可され、
    別インスタンス(=別プロセスを模擬)からの2回目は必ずBLOCKEDになることを検証する。
    """
    lock_path = tmp_path / "send.lock"
    session = FakeSession()

    first_gateway, _, _ = _connected_gateway(
        monkeypatch,
        tmp_path,
        enable_transmission=True,
        session=session,
        lock_path=lock_path,
        fill_state_name="fills_a.json",
    )
    first_result = first_gateway.place_first_test_order()

    assert first_result.sent is True
    assert lock_path.exists() is True
    assert len(session.client.calls) == 1

    # 別プロセスからの再実行を模擬した、完全に新しいインスタンス。
    # プロセス内one-shot(_attempted)は新規なので無関係。永続ロックだけで防ぐ。
    second_gateway, _, _ = _connected_gateway(
        monkeypatch,
        tmp_path,
        enable_transmission=True,
        session=session,
        lock_path=lock_path,
        fill_state_name="fills_b.json",
    )
    second_result = second_gateway.place_first_test_order()

    assert second_result.sent is False
    assert second_result.status == "BLOCKED_ALREADY_SENT"
    # placeOrderは1回目の1件だけのまま増えていないこと。
    assert len(session.client.calls) == 1


def test_lock_is_released_when_underlying_send_is_not_actually_sent(
    monkeypatch, tmp_path
):
    """内部ガード等でsent=Falseが確定した場合は、正当な再試行を妨げないよう
    永続ロックを解放することを検証する。
    """
    lock_path = tmp_path / "send.lock"
    session = FakeSession()

    def blocked_guard(*args, **kwargs):
        return IbkrPaperOrderGuardResult(
            status="WAITING",
            allowed=False,
            symbol=args[0],
            quantity=args[1],
            message="waiting",
        )

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order",
        blocked_guard,
    )

    gateway = IbkrFirstPaperTestGateway(
        enable_transmission=True,
        fill_state_path=tmp_path / "fills.json",
        lock_path=lock_path,
    )
    assert gateway.connect() is True

    result = gateway.place_first_test_order()

    assert result.sent is False
    assert session.client.calls == []
    # 実際には送信されなかったため、永続ロックは解放され残らない。
    assert lock_path.exists() is False


def test_concurrent_attempts_only_one_process_can_send(monkeypatch, tmp_path):
    """2プロセスが同時に送信を試みても、永続ロックのアトミックな排他作成により
    片方だけがplaceOrderへ到達できることを検証する(スレッドで同時実行を模擬)。
    os.open(O_CREAT|O_EXCL)のアトミック性はカーネルが保証するため、
    プロセス境界に関わらず有効な検証となる。
    """
    lock_path = tmp_path / "send.lock"
    session = FakeSession()

    gateway_a, _, _ = _connected_gateway(
        monkeypatch,
        tmp_path,
        enable_transmission=True,
        session=session,
        lock_path=lock_path,
        fill_state_name="fills_a.json",
    )
    gateway_b, _, _ = _connected_gateway(
        monkeypatch,
        tmp_path,
        enable_transmission=True,
        session=session,
        lock_path=lock_path,
        fill_state_name="fills_b.json",
    )

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def run(name, gateway):
        barrier.wait()
        results[name] = gateway.place_first_test_order()

    t1 = threading.Thread(target=run, args=("a", gateway_a))
    t2 = threading.Thread(target=run, args=("b", gateway_b))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    sent_flags = [results["a"].sent, results["b"].sent]
    assert sent_flags.count(True) == 1
    assert sent_flags.count(False) == 1
    assert len(session.client.calls) == 1


# --- 要件10-11: nextValidId取得 / orderStatus確認 ---


def test_order_id_comes_from_real_ibkr_next_valid_id(monkeypatch, tmp_path):
    gateway, session, _ = _connected_gateway(
        monkeypatch,
        tmp_path,
        enable_transmission=True,
        session=FakeSession(next_order_id=987),
    )

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
