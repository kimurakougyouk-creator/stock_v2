from ai_asset_platform.brokers.ibkr_session import _IbkrPaperClient


def test_error_matches_installed_ibapi_signature():
    """ibapi(10.x)はerror()をreqId, errorTime, errorCode, errorString,
    advancedOrderRejectJsonの5引数で呼ぶ。旧4引数シグネチャのままだと、
    接続直後の情報メッセージでTypeErrorになりnextValidIdを取得できない。
    """
    client = _IbkrPaperClient()

    client.error(-1, 0, 2104, "Market data farm connection is OK", "")
    assert client.ready.is_set() is False

    client.error(-1, 0, 502, "Couldn't connect to TWS", "")
    assert client.ready.is_set() is True


def test_order_status_callback_routes_fill_data():
    received = []
    client = _IbkrPaperClient(
        order_status_handler=lambda *args: received.append(args),
    )

    client.orderStatus(
        123,
        "Submitted",
        1,
        2,
        200.5,
        0,
        0,
        200.5,
        1,
        "",
        0.0,
    )

    assert received == [
        (123, "Submitted", 1.0, 2.0, 200.5),
    ]


def test_order_status_without_handler_is_safe():
    client = _IbkrPaperClient()

    client.orderStatus(
        123,
        "Filled",
        1,
        0,
        201.0,
        0,
        0,
        201.0,
        1,
        "",
        0.0,
    )


class _FakeContract:
    symbol = "AAPL"


class _FakeExecution:
    orderId = 123
    execId = "exec-1"
    shares = 1.0
    price = 100.0


def test_exec_details_callback_routes_execution_data():
    received = []
    client = _IbkrPaperClient(
        exec_details_handler=lambda *args: received.append(args),
    )

    client.execDetails(9001, _FakeContract(), _FakeExecution())

    assert received == [(123, "exec-1", 1.0, 100.0)]


def test_exec_details_without_handler_is_safe():
    client = _IbkrPaperClient()

    client.execDetails(9001, _FakeContract(), _FakeExecution())


def test_order_status_handler_is_unaffected_by_exec_details_handler():
    """execDetailsハンドラの追加後もorderStatus経路が壊れていないこと。"""
    received = []
    client = _IbkrPaperClient(
        order_status_handler=lambda *args: received.append(args),
    )

    client.orderStatus(
        123,
        "Submitted",
        1,
        2,
        200.5,
        0,
        0,
        200.5,
        1,
        "",
        0.0,
    )

    assert received == [(123, "Submitted", 1.0, 2.0, 200.5)]
