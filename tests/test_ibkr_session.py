import pytest

from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
)
from ai_asset_platform.brokers.ibkr_session import (
    IbkrPaperSession,
    _IbkrPaperClient,
    _run_message_loop,
    open_ibkr_paper_session,
)


def test_session_rejects_non_paper_config():
    config = IbkrConnectionConfig(
        port=7496,
        paper_trading=False,
        allow_live_trading=True,
    )

    with pytest.raises(
        RuntimeError,
        match="Paper Trading設定ではない",
    ):
        open_ibkr_paper_session(config)


def test_session_rejects_live_permission():
    config = IbkrConnectionConfig(
        paper_trading=True,
        allow_live_trading=True,
    )

    with pytest.raises(
        RuntimeError,
        match="Live Trading許可中",
    ):
        open_ibkr_paper_session(config)


def test_managed_accounts_callback_captures_account_list():
    client = _IbkrPaperClient()
    assert client.accounts == []

    client.managedAccounts("DUR570982")
    assert client.accounts == ["DUR570982"]


def test_managed_accounts_callback_splits_multiple_accounts():
    client = _IbkrPaperClient()

    client.managedAccounts("DUR570982,DUR999999,")
    assert client.accounts == ["DUR570982", "DUR999999"]


# --- error()コールバック: 全コード・全メッセージを捕捉する ---


def test_error_callback_captures_every_code_not_just_connectivity_ones():
    """4つの接続系コード以外も握りつぶさずerrorsへ記録すること。"""
    client = _IbkrPaperClient()

    client.error(1, 0, 200, "No security definition has been found", "")
    client.error(2, 0, 399, "Order Message: ...", "")
    client.error(-1, 0, 2104, "Market data farm connection is OK", "")

    assert len(client.errors) == 3
    assert client.errors[0] == {
        "req_id": 1,
        "error_time": 0,
        "code": 200,
        "message": "No security definition has been found",
        "advanced_order_reject_json": "",
    }
    assert [e["code"] for e in client.errors] == [200, 399, 2104]


def test_error_callback_still_sets_ready_for_connectivity_codes_only():
    """既存の接続確立用ready.set()挙動を壊していないことを確認する。"""
    client = _IbkrPaperClient()

    client.error(-1, 0, 200, "unrelated error", "")
    assert client.ready.is_set() is False

    client.error(-1, 0, 1100, "Connectivity between IB and TWS has been lost.", "")
    assert client.ready.is_set() is True
    # そしてそのコードもerrorsへ記録されていること(以前は握りつぶされていた)。
    assert any(e["code"] == 1100 for e in client.errors)


# --- openOrder()コールバック: 観測のみ、注文の変更・取消はしない ---


def test_open_order_callback_captures_fields():
    class FakeContract:
        symbol = "AAPL"

    class FakeOrder:
        action = "BUY"
        totalQuantity = 1
        orderType = "MKT"

    class FakeOrderState:
        status = "PreSubmitted"

    client = _IbkrPaperClient()
    client.openOrder(1, FakeContract(), FakeOrder(), FakeOrderState())

    assert client.open_orders == {
        1: {
            "order_id": 1,
            "symbol": "AAPL",
            "action": "BUY",
            "quantity": 1.0,
            "order_type": "MKT",
            "status": "PreSubmitted",
        }
    }


def test_open_order_callback_does_not_expose_mutation_methods():
    """観測ハンドラはdictへの記録のみで、cancelOrder等を一切呼ばないこと。"""
    import inspect

    from ai_asset_platform.brokers import ibkr_session

    source = inspect.getsource(ibkr_session._IbkrPaperClient.openOrder)
    assert "cancelOrder" not in source
    assert "placeOrder" not in source


# --- nextValidId: serverVersionも合わせて記録する ---


def test_next_valid_id_also_captures_server_version():
    client = _IbkrPaperClient()
    client.serverVersion_ = 178  # 実接続時のハンドシェイクを模擬

    client.nextValidId(1)

    assert client.next_order_id == 1
    assert client.server_version == 178
    assert client.ready.is_set() is True


# --- execDetails: 生イベントも観測用に保持する ---


def test_exec_details_records_raw_event_even_without_handler():
    class FakeExecution:
        orderId = 1
        execId = "exec-1"
        shares = 1.0
        price = 150.25

    client = _IbkrPaperClient()
    client.execDetails(9999, object(), FakeExecution())

    assert client.executions == [
        {
            "req_id": 9999,
            "order_id": 1,
            "exec_id": "exec-1",
            "shares": 1.0,
            "price": 150.25,
        }
    ]


# --- message loop / reader threadの死活観測 ---


def test_run_message_loop_records_exception_without_propagating():
    """client.run()が例外を出しても、観測用に記録するだけで再送出しないこと。"""

    class ExplodingClient:
        def __init__(self):
            self.message_loop_exception = None
            self.message_loop_finished = __import__("threading").Event()

        def run(self):
            raise RuntimeError("boom")

    client = ExplodingClient()

    _run_message_loop(client)  # 例外が外へ伝播しなければ成功

    assert isinstance(client.message_loop_exception, RuntimeError)
    assert client.message_loop_finished.is_set() is True


def test_ibkr_paper_session_diagnostics_reports_state():
    client = _IbkrPaperClient()
    client.serverVersion_ = 178  # 実接続時のハンドシェイクを模擬
    client.nextValidId(5)  # server_version/next_order_idはここで確定する

    class FakeThread:
        def is_alive(self):
            return True

    session = IbkrPaperSession(
        client=client,
        next_order_id=5,
        thread=FakeThread(),
    )

    diagnostics = session.diagnostics()

    assert diagnostics.server_version == 178
    assert diagnostics.next_valid_id == 5
    assert diagnostics.message_loop_alive is True
    assert diagnostics.message_loop_exception is None


def test_ibkr_paper_session_message_loop_alive_false_without_thread():
    """後方互換: threadを渡さない既存呼び出し側でも安全に動くこと。"""
    client = _IbkrPaperClient()
    session = IbkrPaperSession(client=client, next_order_id=1)

    assert session.message_loop_alive is False


# --- 接続失敗時の観測フック(on_failed_connect): 1回だけ・リトライなし ---


def test_on_failed_connect_is_invoked_once_before_client_is_discarded(monkeypatch):
    """接続がタイムアウトした場合、破棄する直前にon_failed_connectへ
    (client, thread)が1回だけ渡ること。再接続やリトライは一切しないこと。
    """
    from ai_asset_platform.brokers import ibkr_session

    monkeypatch.setattr(
        ibkr_session._IbkrPaperClient,
        "connect",
        lambda self, host, port, client_id: None,
    )

    captured = []

    def on_failed_connect(client, thread):
        captured.append((client, thread))

    config = IbkrConnectionConfig(
        host="127.0.0.1",
        port=4002,
        client_id=999,
        paper_trading=True,
        allow_live_trading=False,
    )

    result = open_ibkr_paper_session(
        config,
        timeout=0.05,
        on_failed_connect=on_failed_connect,
    )

    assert result is None
    assert len(captured) == 1
    client, thread = captured[0]
    assert isinstance(client, _IbkrPaperClient)
    assert client.next_order_id is None


def test_on_failed_connect_not_invoked_when_default(monkeypatch):
    """on_failed_connectを渡さない既存呼び出し側の挙動は変わらないこと。"""
    from ai_asset_platform.brokers import ibkr_session

    monkeypatch.setattr(
        ibkr_session._IbkrPaperClient,
        "connect",
        lambda self, host, port, client_id: None,
    )

    config = IbkrConnectionConfig(
        host="127.0.0.1",
        port=4002,
        client_id=999,
        paper_trading=True,
        allow_live_trading=False,
    )

    result = open_ibkr_paper_session(config, timeout=0.05)

    assert result is None


def test_session_module_does_not_send_orders():
    from pathlib import Path

    text = Path(
        "src/ai_asset_platform/brokers/ibkr_session.py"
    ).read_text(encoding="utf-8")

    assert ".placeOrder(" not in text
    assert "transmit = True" not in text
