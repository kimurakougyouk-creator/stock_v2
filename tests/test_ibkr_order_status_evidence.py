from ai_asset_platform.brokers.ibkr_session import _IbkrPaperClient


def test_order_status_is_buffered_even_without_fill_handler():
    client = _IbkrPaperClient()

    client.orderStatus(
        7,
        "Filled",
        1,
        0,
        123.45,
        999,
        0,
        123.45,
        17,
        "",
        0,
    )

    assert client.order_statuses[7] == {
        "order_id": 7,
        "status": "Filled",
        "filled": 1.0,
        "remaining": 0.0,
        "avg_fill_price": 123.45,
        "perm_id": 999,
        "parent_id": 0,
        "last_fill_price": 123.45,
        "client_id": 17,
        "why_held": "",
        "mkt_cap_price": 0.0,
    }


def test_order_status_buffer_keeps_latest_broker_observation():
    client = _IbkrPaperClient()
    client.orderStatus(7, "Submitted", 0, 1, 0, 999, 0, 0, 17, "", 0)
    client.orderStatus(7, "Filled", 1, 0, 125, 999, 0, 125, 17, "", 0)

    assert client.order_statuses[7]["status"] == "Filled"
    assert client.order_statuses[7]["filled"] == 1.0
    assert client.order_statuses[7]["avg_fill_price"] == 125.0
