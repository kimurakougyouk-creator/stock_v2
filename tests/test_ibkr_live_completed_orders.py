from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_live_completed_orders as subject

from ai_asset_platform.brokers.ibkr_live_completed_orders import (
    IbkrLiveCompletedOrderEvidence,
    IbkrLiveCompletedOrdersSnapshot,
    _dedupe_exact_completed_orders,
    persist_live_completed_orders,
    preview_ibkr_live_completed_orders,
)


def test_missing_confirmation_blocks_before_live_connection():
    snapshot = preview_ibkr_live_completed_orders(
        confirmation="WRONG",
        endpoint_port=4001,
    )

    assert snapshot.attempted is False
    assert snapshot.connected is False
    assert snapshot.ready is False
    assert snapshot.order_sent is False
    assert snapshot.cancel_sent is False
    assert snapshot.modify_sent is False
    assert snapshot.live_order_sent is False


def test_malformed_same_account_completed_callback_marks_evidence_invalid():
    probe = subject._LiveCompletedOrdersProbe()
    probe.accounts = ["DU123"]
    contract = SimpleNamespace(
        symbol="9432",
        secType="STK",
        currency="JPY",
        primaryExchange="TSEJ",
        exchange="TSEJ",
    )
    order = SimpleNamespace(
        account="DU123",
        orderId=77,
        permId=880077,
        clientId=681,
        totalQuantity=float("nan"),
        action="BUY",
        orderType="LMT",
        lmtPrice=400.0,
        orderRef="live-pilot:9432:BUY:100:test",
    )
    order_state = SimpleNamespace(
        status="Filled",
        completedStatus="Filled",
        completedTime="20260921 12:39:20 UTC",
    )

    probe.completedOrder(contract, order, order_state)

    assert probe.invalid_order_evidence is True
    assert probe.orders == []


def test_coercible_non_integer_completed_order_identities_are_rejected():
    contract = SimpleNamespace(
        symbol="9432",
        secType="STK",
        currency="JPY",
        primaryExchange="TSEJ",
        exchange="TSEJ",
    )
    order_state = SimpleNamespace(
        status="Cancelled",
        completedStatus="Cancelled",
        completedTime="20260921 12:39:20 UTC",
    )
    base_order = {
        "account": "DU123",
        "orderId": 77,
        "permId": 880077,
        "clientId": 681,
        "totalQuantity": 100.0,
        "action": "BUY",
        "orderType": "LMT",
        "lmtPrice": 400.0,
        "orderRef": "live-pilot:9432:BUY:100:test",
    }

    for field, malformed_value in (
        ("orderId", 77.5),
        ("permId", "880077"),
        ("clientId", True),
    ):
        probe = subject._LiveCompletedOrdersProbe()
        probe.accounts = ["DU123"]
        values = dict(base_order)
        values[field] = malformed_value

        probe.completedOrder(
            contract,
            SimpleNamespace(**values),
            order_state,
        )

        assert probe.invalid_order_evidence is True
        assert probe.orders == []


def test_invalid_completed_order_evidence_blocks_ready_snapshot(monkeypatch):
    class ReadyEvent:
        def wait(self, timeout):
            return True

    class FakeProbe:
        def __init__(self):
            self.connected_ready = ReadyEvent()
            self.accounts_ready = ReadyEvent()
            self.orders_ready = ReadyEvent()
            self.accounts = ["DU123"]
            self.orders = []
            self.errors = []
            self.fatal_error = None
            self.invalid_order_evidence = True

        def connect(self, *args, **kwargs):
            return None

        def reqManagedAccts(self):
            return None

        def reqCompletedOrders(self, api_only):
            assert api_only is False

        def isConnected(self):
            return False

    monkeypatch.setattr(subject, "_LiveCompletedOrdersProbe", FakeProbe)
    monkeypatch.setattr(
        subject,
        "Thread",
        lambda *args, **kwargs: SimpleNamespace(start=lambda: None),
    )

    snapshot = subject.preview_ibkr_live_completed_orders(
        confirmation=subject.CONFIRMATION_VALUE,
        endpoint_port=4001,
    )

    assert snapshot.attempted is True
    assert snapshot.connected is True
    assert snapshot.ready is False
    assert snapshot.orders == ()
    assert snapshot.blocked_reason == (
        "Live completed-order snapshot contained malformed order evidence"
    )
    assert snapshot.order_sent is False
    assert snapshot.cancel_sent is False
    assert snapshot.modify_sent is False
    assert snapshot.live_order_sent is False


def test_persisted_completed_order_report_never_exposes_raw_account_id(tmp_path: Path):
    fingerprint = "a" * 64
    snapshot = IbkrLiveCompletedOrdersSnapshot(
        attempted=True,
        connected=True,
        ready=True,
        endpoint_port=4001,
        account_fingerprint=fingerprint,
        orders=(
            IbkrLiveCompletedOrderEvidence(
                order_id=77,
                perm_id=880077,
                client_id=681,
                symbol="9432",
                sec_type="STK",
                currency="JPY",
                exchange="TSEJ",
                action="BUY",
                quantity=100.0,
                order_type="LMT",
                limit_price=400.0,
                status="Cancelled",
                completed_status="Cancelled",
                completed_time="20260921 12:39:20 UTC",
                order_ref="live-pilot:9432:BUY:100:test",
                account_fingerprint=fingerprint,
            ),
        ),
    )
    path = tmp_path / "completed.json"

    persist_live_completed_orders(snapshot, report_path=path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["ready"] is True
    assert payload["raw_account_id_persisted"] is False
    assert payload["order_sent"] is False
    assert payload["cancel_sent"] is False
    assert payload["modify_sent"] is False
    assert payload["live_order_sent"] is False
    assert "account" not in payload["orders"][0]
    assert payload["orders"][0]["account_fingerprint"] == fingerprint


def test_exact_dedup_preserves_conflicting_completed_order_callbacks():
    fingerprint = "a" * 64
    base = IbkrLiveCompletedOrderEvidence(
        order_id=77,
        perm_id=880077,
        client_id=681,
        symbol="9432",
        sec_type="STK",
        currency="JPY",
        exchange="TSEJ",
        action="BUY",
        quantity=100.0,
        order_type="LMT",
        limit_price=400.0,
        status="Cancelled",
        completed_status="Cancelled",
        completed_time="20260921 12:39:20 UTC",
        order_ref="live-pilot:9432:BUY:100:test",
        account_fingerprint=fingerprint,
    )
    conflicting = replace(
        base,
        status="Filled",
        completed_status="Filled",
        completed_time="20260921 12:39:21 UTC",
    )

    observed = _dedupe_exact_completed_orders([base, base, conflicting])

    assert observed == (base, conflicting)
    assert {item.status for item in observed} == {"Cancelled", "Filled"}
