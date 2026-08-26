from pathlib import Path
from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_all_open_orders_snapshot as module


def test_open_order_callback_captures_manual_review_evidence():
    probe = module._AllOpenOrdersProbe()
    contract = SimpleNamespace(
        symbol="spy",
        localSymbol="SPY",
        secType="STK",
        currency="USD",
        exchange="SMART",
    )
    order = SimpleNamespace(
        action="BUY",
        totalQuantity=1,
        orderType="LMT",
        clientId=9,
        permId=1234,
    )
    state = SimpleNamespace(status="PreSubmitted")

    probe.openOrder(77, contract, order, state)

    assert probe.orders == [
        module.IbkrOpenOrderEvidence(
            order_id=77,
            symbol="SPY",
            local_symbol="SPY",
            sec_type="STK",
            currency="USD",
            exchange="SMART",
            action="BUY",
            quantity=1.0,
            order_type="LMT",
            status="PreSubmitted",
            client_id=9,
            perm_id=1234,
        )
    ]


def test_open_order_end_marks_snapshot_ready():
    probe = module._AllOpenOrdersProbe()
    assert not probe.orders_ready.is_set()
    probe.openOrderEnd()
    assert probe.orders_ready.is_set()


def test_fatal_connection_error_releases_waiters():
    probe = module._AllOpenOrdersProbe()
    probe.error(-1, 502, "could not connect")
    assert probe.fatal is True
    assert probe.connected_ready.is_set()
    assert probe.orders_ready.is_set()


def test_snapshot_module_is_strictly_read_only():
    text = Path(module.__file__).read_text(encoding="utf-8")
    assert "reqAllOpenOrders()" in text
    assert ".placeOrder(" not in text
    assert ".cancelOrder(" not in text
    assert "AI_ASSET_VERIFIED_PAPER_RUNTIME_CONFIRM" not in text
