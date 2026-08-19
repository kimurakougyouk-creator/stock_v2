from dataclasses import dataclass, field
from typing import Callable

from ai_asset_platform.brokers.ibkr_first_paper_test import REQUIRED_ACCOUNT_ID
from ai_asset_platform.brokers.ibkr_first_paper_test_confirmation import (
    reconcile_order_via_readonly_query,
    send_and_confirm_first_paper_order,
)
from ai_asset_platform.brokers.ibkr_fill_state import IbkrFillStateStore
from ai_asset_platform.brokers.ibkr_paper_order_guard import (
    IbkrPaperOrderGuardResult,
)
from ai_asset_platform.brokers.ibkr_session import IbkrConnectionDiagnostics


def _emit_order_status(client, order_id, status, filled, remaining, avg_price):
    """実ibapiのEWrapper.orderStatus()と同じ11引数フルシグネチャで発火する。"""
    client.orderStatus(
        order_id, status, filled, remaining, avg_price, 0, 0, 0.0, 0, "", 0.0
    )


def _ready_guard(*args, **kwargs):
    return IbkrPaperOrderGuardResult(
        status="READY",
        allowed=True,
        symbol=args[0],
        quantity=args[1],
        message="ready",
    )


class FakeContract:
    symbol = "AAPL"


class FakeExecution:
    def __init__(self, order_id, exec_id, shares, price):
        self.orderId = order_id
        self.execId = exec_id
        self.shares = shares
        self.price = price


class FakeOrder:
    def __init__(self, order_id):
        self.orderId = order_id


class FakeOrderState:
    status = "Cancelled"


@dataclass
class FakeClient:
    calls: list = field(default_factory=list)
    connected: bool = True
    accounts: list = field(default_factory=lambda: [REQUIRED_ACCOUNT_ID])
    server_version: int | None = 178
    order_status_handler: Callable | None = None
    exec_details_handler: Callable | None = None
    exec_calls: list = field(default_factory=list)
    completed_calls: list = field(default_factory=list)
    error_calls: list = field(default_factory=list)
    # ===== 観測専用バッファ(実_IbkrPaperClientと同じ役割を模倣する) =====
    errors: list = field(default_factory=list)
    open_orders: dict = field(default_factory=dict)
    executions: list = field(default_factory=list)

    def placeOrder(self, order_id, contract, order):  # noqa: N802
        self.calls.append((order_id, contract, order))

    def isConnected(self):  # noqa: N802
        return self.connected

    def disconnect(self):
        self.connected = False

    # ===== 以下はすべて実ibapiのEWrapperコールバックと同じシグネチャ =====

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
                int(orderId),
                str(status),
                float(filled),
                float(remaining),
                float(avgFillPrice),
            )

    def execDetails(self, reqId, contract, execution):  # noqa: N802
        self.exec_calls.append((reqId, contract, execution))
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

    def execDetailsEnd(self, reqId):  # noqa: N802
        pass

    def openOrder(self, orderId, contract, order, orderState):  # noqa: N802
        self.open_orders[int(orderId)] = {
            "order_id": int(orderId),
            "symbol": getattr(contract, "symbol", None),
            "action": getattr(order, "action", None),
            "quantity": float(getattr(order, "totalQuantity", 0) or 0),
            "order_type": getattr(order, "orderType", None),
            "status": getattr(orderState, "status", None),
        }

    def completedOrder(self, contract, order, orderState):  # noqa: N802
        self.completed_calls.append((contract, order, orderState))

    def completedOrdersEnd(self):  # noqa: N802
        pass

    def error(  # noqa: N802
        self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""
    ):
        self.error_calls.append(errorCode)
        self.errors.append(
            {
                "req_id": reqId,
                "error_time": errorTime,
                "code": int(errorCode),
                "message": str(errorString),
                "advanced_order_reject_json": advancedOrderRejectJson,
            }
        )

    def reqExecutions(self, reqId, execFilter):  # noqa: N802
        pass

    def reqCompletedOrders(self, apiOnly):  # noqa: N802
        pass


@dataclass
class FakeSession:
    client: FakeClient = field(default_factory=FakeClient)
    next_order_id: int = 700
    connected: bool = True
    message_loop_alive: bool = True

    def disconnect(self):
        self.connected = False

    def diagnostics(self) -> IbkrConnectionDiagnostics:
        return IbkrConnectionDiagnostics(
            server_version=self.client.server_version,
            next_valid_id=self.client.next_order_id
            if hasattr(self.client, "next_order_id")
            else self.next_order_id,
            is_connected=self.client.isConnected(),
            message_loop_alive=self.message_loop_alive,
            message_loop_exception=None,
        )


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _patch_send_path(monkeypatch, session):
    def fake_open(config, *, order_status_handler=None, exec_details_handler=None):
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


# --- 終端状態(FILLED)の即時検知 ---


def test_immediate_fill_via_order_status_exits_without_sleeping(monkeypatch, tmp_path):
    """
    orderStatus(Filled)が、送信・登録が完了した直後(監視ループ開始前)に
    届いた場合、1回もsleepせずに終端検知できることを検証する。

    register_order()はplace_first_test_order()内部でplaceOrder呼び出し後に
    実行されるため、ここでは(現実の非同期到着を模した)now_fn経由で
    送信完了後にイベントを発火させる。
    """
    session = FakeSession()
    _patch_send_path(monkeypatch, session)
    clock = FakeClock()
    emitted = {"done": False}

    def now_fn():
        if session.client.calls and not emitted["done"]:
            emitted["done"] = True
            order_id = session.client.calls[0][0]
            _emit_order_status(session.client, order_id, "Filled", 1.0, 0.0, 150.0)
        return clock.now()

    sleep_calls = []

    result = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        now_fn=now_fn,
        sleep_fn=lambda dt: sleep_calls.append(dt),
    )

    assert result.status == "TERMINAL"
    assert result.reached_terminal is True
    assert result.timed_out is False
    assert result.last_known_status == "Filled"
    assert result.filled_quantity == 1.0
    assert sleep_calls == []
    assert len(session.client.calls) == 1


# --- orderStatus遅延: 数回のポーリング後に届く ---


def test_delayed_order_status_is_captured_before_timeout(monkeypatch, tmp_path):
    session = FakeSession()
    _patch_send_path(monkeypatch, session)
    clock = FakeClock()

    def sleep_fn(dt):
        clock.advance(dt)
        if clock.t >= 1.5 and not sleep_fn.fired:
            sleep_fn.fired = True
            order_id = session.client.calls[0][0]
            _emit_order_status(session.client, order_id, "Filled", 1.0, 0.0, 150.0)

    sleep_fn.fired = False

    result = send_and_confirm_first_paper_order(
        timeout_seconds=30.0,
        poll_interval_seconds=0.5,
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        now_fn=clock.now,
        sleep_fn=sleep_fn,
    )

    assert result.status == "TERMINAL"
    assert result.reached_terminal is True
    assert result.last_known_status == "Filled"


# --- execDetailsのみ届く場合(orderStatusは一度も呼ばれない) ---


def test_terminal_via_exec_details_only(monkeypatch, tmp_path):
    session = FakeSession()
    _patch_send_path(monkeypatch, session)
    clock = FakeClock()

    def sleep_fn(dt):
        clock.advance(dt)
        if clock.t >= 0.5 and not sleep_fn.fired:
            sleep_fn.fired = True
            order_id = session.client.calls[0][0]
            session.client.execDetails(
                9999, FakeContract(), FakeExecution(order_id, "exec-1", 1.0, 150.0)
            )

    sleep_fn.fired = False

    result = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        now_fn=clock.now,
        sleep_fn=sleep_fn,
    )

    assert result.status == "TERMINAL"
    assert result.reached_terminal is True
    # orderStatusは一度も発火していないため last_known_status は不明のまま。
    assert result.last_known_status is None
    assert result.filled_quantity == 1.0


# --- Cancelled(約定ゼロ)も終端として即終了 ---


def test_cancelled_status_with_zero_fill_is_terminal(monkeypatch, tmp_path):
    session = FakeSession()
    _patch_send_path(monkeypatch, session)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        _emit_order_status(session.client, order_id, "Cancelled", 0.0, 0.0, 0.0)

    session.client.placeOrder = fake_place_order

    result = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert result.status == "TERMINAL"
    assert result.last_known_status == "Cancelled"
    assert result.filled_quantity == 0.0


# --- timeout: 無限待機せず打ち切る ---


def test_timeout_when_never_reaching_terminal_state(monkeypatch, tmp_path):
    session = FakeSession()
    _patch_send_path(monkeypatch, session)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        _emit_order_status(session.client, order_id, "PreSubmitted", 0.0, 1.0, 0.0)

    session.client.placeOrder = fake_place_order

    result = send_and_confirm_first_paper_order(
        timeout_seconds=5.0,
        poll_interval_seconds=1.0,
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert result.status == "TIMEOUT"
    assert result.reached_terminal is False
    assert result.timed_out is True
    assert result.last_known_status == "PreSubmitted"


# --- 観測機能: error/openOrder/execDetails/診断情報を握りつぶさず報告する ---


def test_uncommon_error_code_is_captured_not_swallowed(monkeypatch, tmp_path):
    """以前は502/503/504/1100以外のエラーコードが完全に握りつぶされていた。
    観測機能追加後は、監視ウィンドウ中に届いた任意のエラーコードが
    result.errorsへ残ること、かつplaceOrderの回数には影響しないことを検証する。
    """
    session = FakeSession()
    _patch_send_path(monkeypatch, session)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        # 200 = No security definition has been found (以前は完全に不可視だった)
        session.client.error(order_id, 0, 200, "No security definition found", "")
        _emit_order_status(session.client, order_id, "Filled", 1.0, 0.0, 150.0)

    session.client.placeOrder = fake_place_order

    result = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert result.status == "TERMINAL"
    assert len(session.client.calls) == 1
    assert any(e["code"] == 200 for e in result.errors)
    assert result.errors[0]["message"] == "No security definition found"


def test_open_order_seen_during_monitoring_is_surfaced(monkeypatch, tmp_path):
    class FakeOrderState:
        status = "PreSubmitted"

    session = FakeSession()
    _patch_send_path(monkeypatch, session)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        session.client.openOrder(order_id, contract, order, FakeOrderState())
        _emit_order_status(session.client, order_id, "Filled", 1.0, 0.0, 150.0)

    session.client.placeOrder = fake_place_order

    result = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert len(session.client.calls) == 1
    assert result.order_id in result.open_orders
    assert result.open_orders[result.order_id]["status"] == "PreSubmitted"


def test_diagnostics_reports_server_version_and_next_valid_id(monkeypatch, tmp_path):
    session = FakeSession(client=FakeClient(server_version=178), next_order_id=42)
    _patch_send_path(monkeypatch, session)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        _emit_order_status(session.client, order_id, "Filled", 1.0, 0.0, 150.0)

    session.client.placeOrder = fake_place_order

    result = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert result.diagnostics is not None
    assert result.diagnostics.server_version == 178
    assert result.diagnostics.is_connected is True


def test_observability_does_not_trigger_place_order_when_blocked(monkeypatch, tmp_path):
    """口座不一致でBLOCKEDになるケースでも、観測データは収集されるが
    placeOrderは1回も呼ばれないこと(観測機能追加が安全装置を弱めていない)。
    """
    session = FakeSession(client=FakeClient(accounts=["OTHER_ACCOUNT"]))
    _patch_send_path(monkeypatch, session)

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))

    session.client.placeOrder = fake_place_order

    result = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        account_verification_timeout=0.05,
    )

    assert result.status == "NOT_SENT"
    assert result.send_result.status == "BLOCKED_ACCOUNT_MISMATCH"
    assert session.client.calls == []
    assert result.diagnostics is not None


# --- 接続失敗時は送信しない ---


def test_connection_failure_never_sends(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: None,
    )

    result = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
    )

    assert result.status == "CONNECTION_FAILED"
    assert result.send_result.sent is False


# --- 送信直前の口座確認: 不一致なら送信しない ---


def test_account_mismatch_never_sends(monkeypatch, tmp_path):
    session = FakeSession(client=FakeClient(accounts=["OTHER_ACCOUNT"]))
    _patch_send_path(monkeypatch, session)

    result = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=tmp_path / "send.lock",
        account_verification_timeout=0.05,
    )

    assert result.status == "NOT_SENT"
    assert result.send_result.sent is False
    assert result.send_result.status == "BLOCKED_ACCOUNT_MISMATCH"
    assert session.client.calls == []


# --- 永続one-shotロック: 2回目はBLOCKED、placeOrderは増えない ---


def test_second_invocation_is_blocked_by_persistent_lock(monkeypatch, tmp_path):
    session = FakeSession()
    _patch_send_path(monkeypatch, session)
    clock = FakeClock()

    def fake_place_order(order_id, contract, order):
        session.client.calls.append((order_id, contract, order))
        _emit_order_status(session.client, order_id, "Filled", 1.0, 0.0, 150.0)

    session.client.placeOrder = fake_place_order

    lock_path = tmp_path / "send.lock"

    first = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=lock_path,
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    # 1回目のdisconnect()で切断済みのセッションを、2回目の新規接続として再利用する。
    session.connected = True
    session.client.connected = True

    second = send_and_confirm_first_paper_order(
        fill_state_path=tmp_path / "fills.json",
        lock_path=lock_path,
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert first.send_result.sent is True
    assert second.send_result.sent is False
    assert second.send_result.status == "BLOCKED_ALREADY_SENT"
    assert len(session.client.calls) == 1


# =====================================================================
# reconcile_order_via_readonly_query
# =====================================================================


def _patch_reconciliation_path(monkeypatch, session):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: session,
    )


def test_reconciliation_reports_diagnostics_and_full_error_events(
    monkeypatch, tmp_path
):
    session = FakeSession(client=FakeClient(server_version=178))

    def fake_req_executions(reqId, execFilter):
        session.client.error(reqId, 0, 321, "read-only API")
        session.client.execDetailsEnd(reqId)

    def fake_req_completed(apiOnly):
        session.client.completedOrdersEnd()

    session.client.reqExecutions = fake_req_executions
    session.client.reqCompletedOrders = fake_req_completed
    _patch_reconciliation_path(monkeypatch, session)

    result = reconcile_order_via_readonly_query(
        1,
        fill_state_path=tmp_path / "fills.json",
        now_fn=lambda: 0.0,
        sleep_fn=lambda dt: None,
    )

    assert result.diagnostics is not None
    assert result.diagnostics.server_version == 178
    assert result.diagnostics.is_connected is True
    assert any(
        e["code"] == 321 and e["message"] == "read-only API"
        for e in result.error_events
    )


def test_reconciliation_found_via_executions_and_persists(monkeypatch, tmp_path):
    session = FakeSession()

    def fake_req_executions(reqId, execFilter):
        session.client.execDetails(
            reqId, FakeContract(), FakeExecution(1, "exec-1", 1.0, 150.0)
        )
        session.client.execDetailsEnd(reqId)

    def fake_req_completed(apiOnly):
        session.client.completedOrdersEnd()

    session.client.reqExecutions = fake_req_executions
    session.client.reqCompletedOrders = fake_req_completed
    _patch_reconciliation_path(monkeypatch, session)

    fill_state_path = tmp_path / "fills.json"

    result = reconcile_order_via_readonly_query(
        1,
        fill_state_path=fill_state_path,
        now_fn=lambda: 0.0,
        sleep_fn=lambda dt: None,
    )

    assert result.status == "FOUND"
    assert result.executions_found == [
        {"execId": "exec-1", "shares": 1.0, "price": 150.0}
    ]
    assert result.timed_out is False

    # 見つかった約定が永続状態へ反映されていること。
    store = IbkrFillStateStore(fill_state_path)
    assert store.load() == {1: 1.0}


def test_reconciliation_found_via_completed_order_only(monkeypatch, tmp_path):
    session = FakeSession()

    def fake_req_executions(reqId, execFilter):
        session.client.execDetailsEnd(reqId)

    def fake_req_completed(apiOnly):
        session.client.completedOrder(FakeContract(), FakeOrder(1), FakeOrderState())
        session.client.completedOrdersEnd()

    session.client.reqExecutions = fake_req_executions
    session.client.reqCompletedOrders = fake_req_completed
    _patch_reconciliation_path(monkeypatch, session)

    result = reconcile_order_via_readonly_query(
        1,
        fill_state_path=tmp_path / "fills.json",
        now_fn=lambda: 0.0,
        sleep_fn=lambda dt: None,
    )

    assert result.status == "FOUND"
    assert result.completed_order_found is True


def test_reconciliation_zero_results_is_unknown_not_cancelled(monkeypatch, tmp_path):
    """今回の実案件と同じ状況: 正常応答・0件はUNKNOWNであり、
    取消/失効/未約定と断定しないこと。
    """
    session = FakeSession()

    def fake_req_executions(reqId, execFilter):
        session.client.execDetailsEnd(reqId)

    def fake_req_completed(apiOnly):
        session.client.completedOrdersEnd()

    session.client.reqExecutions = fake_req_executions
    session.client.reqCompletedOrders = fake_req_completed
    _patch_reconciliation_path(monkeypatch, session)

    result = reconcile_order_via_readonly_query(
        1,
        fill_state_path=tmp_path / "fills.json",
        now_fn=lambda: 0.0,
        sleep_fn=lambda dt: None,
    )

    assert result.status == "UNKNOWN"
    assert result.executions_found == []
    assert result.completed_order_found is False
    assert result.error_codes == []
    assert result.timed_out is False
    assert "未約定・取消・失効とは断定せず" in result.message


def test_reconciliation_error_code_results_in_error_status(monkeypatch, tmp_path):
    session = FakeSession()

    def fake_req_executions(reqId, execFilter):
        session.client.error(reqId, 0, 321, "read-only API")
        session.client.execDetailsEnd(reqId)

    def fake_req_completed(apiOnly):
        session.client.completedOrdersEnd()

    session.client.reqExecutions = fake_req_executions
    session.client.reqCompletedOrders = fake_req_completed
    _patch_reconciliation_path(monkeypatch, session)

    result = reconcile_order_via_readonly_query(
        1,
        fill_state_path=tmp_path / "fills.json",
        now_fn=lambda: 0.0,
        sleep_fn=lambda dt: None,
    )

    assert result.status == "ERROR"
    assert 321 in result.error_codes


def test_reconciliation_benign_info_codes_do_not_cause_error(monkeypatch, tmp_path):
    session = FakeSession()

    def fake_req_executions(reqId, execFilter):
        session.client.error(reqId, 0, 2104, "market data farm connection is OK")
        session.client.error(reqId, 0, 2107, "HMDS data farm connection is inactive")
        session.client.execDetailsEnd(reqId)

    def fake_req_completed(apiOnly):
        session.client.completedOrdersEnd()

    session.client.reqExecutions = fake_req_executions
    session.client.reqCompletedOrders = fake_req_completed
    _patch_reconciliation_path(monkeypatch, session)

    result = reconcile_order_via_readonly_query(
        1,
        fill_state_path=tmp_path / "fills.json",
        now_fn=lambda: 0.0,
        sleep_fn=lambda dt: None,
    )

    assert result.status == "UNKNOWN"
    assert 2104 in result.error_codes
    assert 2107 in result.error_codes


def test_reconciliation_timeout_when_ends_never_fire(tmp_path, monkeypatch):
    session = FakeSession()

    # reqExecutions/reqCompletedOrdersが何も応答しない(End markerが来ない)状況。
    session.client.reqExecutions = lambda reqId, execFilter: None
    session.client.reqCompletedOrders = lambda apiOnly: None
    _patch_reconciliation_path(monkeypatch, session)

    clock = FakeClock()

    result = reconcile_order_via_readonly_query(
        1,
        fill_state_path=tmp_path / "fills.json",
        timeout_seconds=3.0,
        now_fn=clock.now,
        sleep_fn=lambda dt: clock.advance(dt),
    )

    assert result.status == "UNKNOWN"
    assert result.timed_out is True


def test_reconciliation_connection_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr.open_ibkr_paper_session",
        lambda config, **kwargs: None,
    )

    result = reconcile_order_via_readonly_query(
        1,
        fill_state_path=tmp_path / "fills.json",
    )

    assert result.status == "CONNECTION_FAILED"


def test_reconciliation_place_order_guard_raises_if_triggered(monkeypatch, tmp_path):
    """安全装置の検証: 何らかの理由でplaceOrderが呼ばれたら即例外になること。"""
    session = FakeSession()

    def fake_req_executions(reqId, execFilter):
        # 本来あり得ないが、安全装置が機能することを直接検証する。
        session.client.placeOrder(999, FakeContract(), FakeOrder(999))

    session.client.reqExecutions = fake_req_executions
    session.client.reqCompletedOrders = lambda apiOnly: None
    _patch_reconciliation_path(monkeypatch, session)

    import pytest

    with pytest.raises(RuntimeError, match="SAFETY ABORT"):
        reconcile_order_via_readonly_query(
            1,
            fill_state_path=tmp_path / "fills.json",
            now_fn=lambda: 0.0,
            sleep_fn=lambda dt: None,
        )
