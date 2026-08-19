from dataclasses import dataclass, field
from typing import Callable

from ai_asset_platform.brokers.ibkr import (
    DEFAULT_ASYNC_ORDER_TIMEOUT_SECONDS,
    IbkrBrokerAdapter,
)
from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_paper_order_guard import (
    IbkrPaperOrderGuardResult,
)
from ai_asset_platform.brokers.ibkr_session import IbkrConnectionDiagnostics
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide


class FakeContract:
    symbol = "AAPL"


class FakeExecution:
    def __init__(self, order_id, exec_id, shares, price):
        self.orderId = order_id
        self.execId = exec_id
        self.shares = shares
        self.price = price


class FakeOrderState:
    def __init__(self, status="PreSubmitted"):
        self.status = status


def _ready_guard(*args, **kwargs):
    return IbkrPaperOrderGuardResult(
        status="READY",
        allowed=True,
        symbol=args[0],
        quantity=args[1],
        message="ready",
    )


@dataclass
class FakeClient:
    calls: list = field(default_factory=list)
    connected: bool = True
    server_version: int | None = 223
    order_status_handler: Callable | None = None
    exec_details_handler: Callable | None = None
    errors: list = field(default_factory=list)
    open_orders: dict = field(default_factory=dict)
    executions: list = field(default_factory=list)

    def placeOrder(self, order_id, contract, order):  # noqa: N802
        self.calls.append((order_id, contract, order))

    def isConnected(self):  # noqa: N802
        return self.connected

    def disconnect(self):
        self.connected = False

    def orderStatus(  # noqa: N802
        self,
        orderId,
        status,
        filled,
        remaining,
        avgFillPrice,
        permId=0,
        parentId=0,
        lastFillPrice=0.0,
        clientId=0,
        whyHeld="",
        mktCapPrice=0.0,
    ):
        if self.order_status_handler is not None:
            self.order_status_handler(
                int(orderId), str(status), float(filled), float(remaining), float(avgFillPrice)
            )

    def openOrder(self, orderId, contract, order, orderState):  # noqa: N802
        self.open_orders[int(orderId)] = {
            "order_id": int(orderId),
            "symbol": getattr(contract, "symbol", None),
            "action": getattr(order, "action", None),
            "quantity": float(getattr(order, "totalQuantity", 0) or 0),
            "order_type": getattr(order, "orderType", None),
            "status": getattr(orderState, "status", None),
        }

    def execDetails(self, reqId, contract, execution):  # noqa: N802
        self.executions.append(
            {
                "req_id": reqId,
                "order_id": int(execution.orderId),
                "exec_id": str(execution.execId),
                "shares": float(execution.shares),
                "price": float(execution.price),
            }
        )
        if self.exec_details_handler is not None:
            self.exec_details_handler(
                int(execution.orderId),
                str(execution.execId),
                float(execution.shares),
                float(execution.price),
            )

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):  # noqa: N802
        self.errors.append(
            {
                "req_id": reqId,
                "error_time": errorTime,
                "code": int(errorCode),
                "message": str(errorString),
                "advanced_order_reject_json": advancedOrderRejectJson,
            }
        )


@dataclass
class FakeSession:
    client: FakeClient = field(default_factory=FakeClient)
    next_order_id: int = 900
    connected: bool = True

    def disconnect(self):
        self.connected = False

    def diagnostics(self) -> IbkrConnectionDiagnostics:
        return IbkrConnectionDiagnostics(
            server_version=self.client.server_version,
            next_valid_id=self.next_order_id,
            is_connected=self.client.isConnected(),
            message_loop_alive=True,
            message_loop_exception=None,
        )


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _patch_open(monkeypatch, session):
    def fake_open(config, *, order_status_handler=None, exec_details_handler=None, **kwargs):
        session.client.order_status_handler = order_status_handler
        session.client.exec_details_handler = exec_details_handler
        return session

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        fake_open,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order",
        _ready_guard,
    )


def _connected_adapter(monkeypatch, tmp_path, session=None, fill_state_name="fills.json"):
    session = session or FakeSession()
    _patch_open(monkeypatch, session)

    adapter = IbkrBrokerAdapter(
        enable_paper_order_transmission=True,
        fill_state_path=tmp_path / fill_state_name,
    )
    assert adapter.connect() is True
    return adapter, session


def _order():
    return OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)


# --- 正常Filled ---


def test_successful_fill_via_open_order_status(monkeypatch, tmp_path):
    adapter, session = _connected_adapter(monkeypatch, tmp_path)
    clock = FakeClock()
    emitted = {"done": False}

    session.client.placeOrder = lambda order_id, contract, order: session.client.calls.append(
        (order_id, contract, order)
    )

    def sleep_fn(dt):
        clock.advance(dt)
        if not emitted["done"]:
            emitted["done"] = True
            order_id, contract, order = session.client.calls[0]
            # register_order()はplace_order()内でplaceOrder呼び出し後に実行
            # されるため、現実の非同期到着と同様、監視ループ側で発火させる。
            session.client.openOrder(order_id, contract, order, FakeOrderState("Filled"))
            session.client.execDetails(
                9999, FakeContract(), FakeExecution(order_id, "exec-1", 1.0, 150.25)
            )

    result = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-1",
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=sleep_fn,
    )

    assert result.status == "TERMINAL"
    assert result.sent is True
    assert result.reached_terminal is True
    assert result.timed_out is False
    assert result.last_known_status == "Filled"
    assert result.filled_quantity == 1.0
    assert result.avg_fill_price == 150.25
    assert len(session.client.calls) == 1


# --- timeout ---


def test_timeout_when_never_reaching_terminal(monkeypatch, tmp_path):
    adapter, session = _connected_adapter(monkeypatch, tmp_path)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        session.client.openOrder(order_id, contract, order, FakeOrderState("PreSubmitted"))

    session.client.placeOrder = fake_place_order

    result = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-2",
        timeout_seconds=5.0,
        poll_interval_seconds=1.0,
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert result.status == "TIMEOUT"
    assert result.sent is True
    assert result.reached_terminal is False
    assert result.timed_out is True
    assert result.last_known_status == "PreSubmitted"
    assert len(session.client.calls) == 1


# --- timeout後の再送0回(同じ呼び出し1回のみでも検証、明示的に再呼び出しなしを確認) ---


def test_no_resend_call_is_made_by_the_method_itself(monkeypatch, tmp_path):
    adapter, session = _connected_adapter(monkeypatch, tmp_path)
    clock = FakeClock()

    session.client.placeOrder = lambda order_id, contract, order: session.client.calls.append(
        (order_id, contract, order)
    )

    adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-3",
        timeout_seconds=2.0,
        poll_interval_seconds=1.0,
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    # 監視ループ内でsleep_fnが複数回呼ばれてもplaceOrderは増えないこと。
    assert len(session.client.calls) == 1


# --- error ---


def test_error_events_are_captured_and_returned(monkeypatch, tmp_path):
    adapter, session = _connected_adapter(monkeypatch, tmp_path)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        session.client.error(order_id, 0, 200, "No security definition found", "")
        session.client.openOrder(order_id, contract, order, FakeOrderState("Filled"))
        session.client.execDetails(
            9999, FakeContract(), FakeExecution(order_id, "exec-1", 1.0, 100.0)
        )

    session.client.placeOrder = fake_place_order

    result = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-4",
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert any(e["code"] == 200 for e in result.errors)
    assert result.status == "TERMINAL"
    assert len(session.client.calls) == 1


# --- placeOrder最大1回(READY_NOT_SENTでもブロックされても増えないこと) ---


def test_place_order_never_called_when_transmission_disabled(monkeypatch, tmp_path):
    session = FakeSession()
    _patch_open(monkeypatch, session)

    adapter = IbkrBrokerAdapter(
        enable_paper_order_transmission=False,
        fill_state_path=tmp_path / "fills.json",
    )
    assert adapter.connect() is True

    result = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-5",
        intent_lock_dir=tmp_path / "locks",
    )

    assert result.status == "NOT_SENT"
    assert result.sent is False
    assert session.client.calls == []


# --- 重複注文ブロック: プロセス内(同一インスタンス) ---


def test_duplicate_intent_id_blocked_within_same_instance(monkeypatch, tmp_path):
    adapter, session = _connected_adapter(monkeypatch, tmp_path)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        session.client.openOrder(order_id, contract, order, FakeOrderState("Filled"))

    session.client.placeOrder = fake_place_order

    first = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-dup",
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )
    second = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-dup",
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert first.sent is True
    assert second.status == "DUPLICATE_BLOCKED"
    assert second.sent is False
    assert len(session.client.calls) == 1


# --- 重複注文ブロック: プロセス跨ぎ(ロックファイルの事前存在で模擬) ---


def test_duplicate_intent_id_blocked_across_process_via_lock_file(monkeypatch, tmp_path):
    from ai_asset_platform.brokers.ibkr import _acquire_intent_lock

    lock_dir = tmp_path / "locks"
    lock_path = lock_dir / "signal-cross-proc.lock"
    assert _acquire_intent_lock(lock_path) is True  # 別プロセスが先に取得した状態を模擬

    adapter, session = _connected_adapter(monkeypatch, tmp_path)

    result = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-cross-proc",
        intent_lock_dir=lock_dir,
    )

    assert result.status == "DUPLICATE_BLOCKED"
    assert session.client.calls == []


# --- 異なるintent_idは互いにブロックしない(生涯1回ロックとの違いを保証) ---


def test_different_intent_ids_are_independent(monkeypatch, tmp_path):
    adapter, session = _connected_adapter(monkeypatch, tmp_path)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        session.client.openOrder(order_id, contract, order, FakeOrderState("Filled"))

    session.client.placeOrder = fake_place_order

    first = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-a",
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )
    second = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-b",
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert first.sent is True
    assert second.sent is True
    assert len(session.client.calls) == 2


# --- NOT_SENTの場合はロックファイルが解放され、正当な再試行を妨げないこと ---


def test_not_sent_releases_lock_for_legitimate_retry(monkeypatch, tmp_path):
    session = FakeSession()

    def blocked_guard(*args, **kwargs):
        return IbkrPaperOrderGuardResult(
            status="WAITING", allowed=False, symbol=args[0], quantity=args[1], message="waiting"
        )

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_paper_transmitter.validate_ibkr_paper_test_order",
        blocked_guard,
    )

    adapter = IbkrBrokerAdapter(
        enable_paper_order_transmission=True,
        fill_state_path=tmp_path / "fills.json",
    )
    assert adapter.connect() is True

    lock_path = tmp_path / "locks" / "signal-retry.lock"
    result = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-retry",
        intent_lock_dir=tmp_path / "locks",
    )

    assert result.status == "NOT_SENT"
    assert lock_path.exists() is False
    assert session.client.calls == []


# --- diagnostics/errors/open_orders/executions反映 ---


def test_diagnostics_and_observability_fields_populated(monkeypatch, tmp_path):
    adapter, session = _connected_adapter(monkeypatch, tmp_path)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        session.client.error(order_id, 0, 2104, "market data farm connection is OK", "")
        session.client.openOrder(order_id, contract, order, FakeOrderState("Filled"))
        session.client.execDetails(
            9999, FakeContract(), FakeExecution(order_id, "exec-1", 1.0, 200.0)
        )

    session.client.placeOrder = fake_place_order

    result = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-diag",
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert result.diagnostics is not None
    assert result.diagnostics.server_version == 223
    assert result.diagnostics.is_connected is True
    assert any(e["code"] == 2104 for e in result.errors)
    assert result.order_id in result.open_orders
    assert result.executions == [
        {
            "req_id": 9999,
            "order_id": result.order_id,
            "exec_id": "exec-1",
            "shares": 1.0,
            "price": 200.0,
        }
    ]


# --- fill state永続化 ---


def test_fill_state_is_persisted_on_execution(monkeypatch, tmp_path):
    from ai_asset_platform.brokers.ibkr_fill_state import IbkrFillStateStore

    adapter, session = _connected_adapter(monkeypatch, tmp_path, fill_state_name="fills.json")
    clock = FakeClock()
    emitted = {"done": False}

    session.client.placeOrder = lambda order_id, contract, order: session.client.calls.append(
        (order_id, contract, order)
    )

    def sleep_fn(dt):
        clock.advance(dt)
        if not emitted["done"]:
            emitted["done"] = True
            order_id, contract, order = session.client.calls[0]
            session.client.openOrder(order_id, contract, order, FakeOrderState("Filled"))
            session.client.execDetails(
                9999, FakeContract(), FakeExecution(order_id, "exec-1", 1.0, 175.5)
            )

    result = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-fillstate",
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=sleep_fn,
    )

    store = IbkrFillStateStore(tmp_path / "fills.json")
    assert store.load() == {result.order_id: 1.0}


# --- TIF=DAY維持(既存prepare_ibkr_paper_orderをそのまま使っていることの確認) ---


def test_tif_day_is_set_on_the_actually_placed_order(monkeypatch, tmp_path):
    adapter, session = _connected_adapter(monkeypatch, tmp_path)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        session.client.openOrder(order_id, contract, order, FakeOrderState("Filled"))

    session.client.placeOrder = fake_place_order

    adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-tif",
        intent_lock_dir=tmp_path / "locks",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    _, _, placed_order = session.client.calls[0]
    assert placed_order.tif == "DAY"
    assert placed_order.transmit is True


# --- Live禁止維持 ---


def test_live_trading_config_is_rejected(monkeypatch, tmp_path):
    session = FakeSession()
    _patch_open(monkeypatch, session)

    adapter = IbkrBrokerAdapter(
        IbkrConnectionConfig(
            host="127.0.0.1",
            port=7496,
            paper_trading=False,
            allow_live_trading=True,
        ),
        enable_paper_order_transmission=True,
        fill_state_path=tmp_path / "fills.json",
    )
    assert adapter.connect() is True

    result = adapter.place_order_and_await_fill(
        _order(),
        order_intent_id="signal-live",
        intent_lock_dir=tmp_path / "locks",
    )

    assert result.status == "NOT_SENT"
    assert result.sent is False
    assert session.client.calls == []


def test_default_timeout_constant_is_thirty_seconds():
    assert DEFAULT_ASYNC_ORDER_TIMEOUT_SECONDS == 30.0
