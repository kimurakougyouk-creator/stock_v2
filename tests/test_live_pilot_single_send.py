from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_asset_platform.execution.live_pilot_single_send as subject
from ai_asset_platform.execution.live_pilot_same_run_preflight import LivePilotSameRunPreflight


PINNED_ACCOUNT = "U_TEST_ONLY"
PINNED_FINGERPRINT = hashlib.sha256(PINNED_ACCOUNT.encode("utf-8")).hexdigest()
APPROVED_SHA = "a" * 40
NOW = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
CHECKED_AT = NOW.isoformat(timespec="seconds")


def _request() -> subject.LivePilotSendRequest:
    return subject.LivePilotSendRequest(
        intent_id="live-pilot:9432:BUY:100:test",
        ticker="9432.T",
        side="BUY",
        quantity=100,
        limit_price=400.0,
        estimated_notional_jpy=40_000.0,
    )


def _readiness() -> dict:
    return {
        "status": "READY_FOR_ONE_OPERATIONAL_PILOT",
        "checked_at": CHECKED_AT,
        "operational_pilot_ready": True,
        "ticker": "9432.T",
        "side": "BUY",
        "quantity": 100,
        "limit_price": 400.0,
        "estimated_notional_jpy": 40_000.0,
        "live_account_ready": True,
        "live_open_orders_ready": True,
        "live_open_order_count": 0,
        "paper_monitor_safe": True,
        "market_session_allowed": True,
        "live_global_lock_intact_during_preparation": True,
        "order_sent": False,
        "live_order_sent": False,
    }


def _preflight(*, ready: bool = True, checked_at: str = CHECKED_AT) -> LivePilotSameRunPreflight:
    return LivePilotSameRunPreflight(
        status="READY_FOR_OPERATOR_AUTHORIZATION" if ready else "BLOCKED",
        checked_at=checked_at,
        blockers=() if ready else ("blocked",),
        ticker="9432.T",
        account_fingerprint_match=ready,
        endpoint_port=4001 if ready else None,
        endpoint_binding_ready=ready,
        evidence_fresh=ready,
        evidence_skew_seconds=1.0 if ready else None,
        operational_readiness_ready=ready,
        paper_monitor_safe=ready,
        emergency_stop_clear=ready,
        live_global_lock_intact=ready,
        ready=ready,
    )


class FakeClient:
    def __init__(
        self,
        *,
        account: str = PINNED_ACCOUNT,
        ack: bool = True,
        place_error: Exception | None = None,
    ):
        from threading import Event

        self.connected_ready = Event()
        self.accounts_ready = Event()
        self.ack_ready = Event()
        self.next_order_id = None
        self.accounts = []
        self.watched_order_id = None
        self.watched_account = None
        self.ack_perm_id = None
        self.broker_status = None
        self.order_error = None
        self.errors = []
        self.account = account
        self.ack = ack
        self.place_error = place_error
        self.place_calls = []
        self.connected = False

    def connect(self, host, port, client_id):
        self.connected = True
        self.next_order_id = 77
        self.connected_ready.set()

    def run(self):
        return None

    def reqManagedAccts(self):
        self.accounts = [self.account]
        self.accounts_ready.set()

    def placeOrder(self, order_id, contract, order):
        self.place_calls.append((order_id, contract, order))
        if self.place_error is not None:
            raise self.place_error
        if self.ack:
            self.broker_status = "Submitted"
            self.ack_perm_id = 880077
            self.ack_ready.set()

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False


def _patch_prereqs(monkeypatch, *, stop_values=(False, False)):
    monkeypatch.setattr(
        subject,
        "audit_live_pilot_source_cutover",
        lambda **kwargs: SimpleNamespace(ready=True),
    )
    values = iter(stop_values)
    monkeypatch.setattr(
        subject,
        "live_pilot_stop_is_active",
        lambda **kwargs: next(values),
    )
    events = []
    monkeypatch.setattr(
        subject,
        "consume_live_pilot_authorization",
        lambda **kwargs: {
            "status": "CONSUMED",
            "intent_id": kwargs["intent_id"],
            "nonce": kwargs["nonce"],
            "order_sent": False,
            "live_order_sent": False,
        },
    )
    monkeypatch.setattr(
        subject,
        "create_consumed_authorization_journal",
        lambda **kwargs: events.append("journal") or {},
    )
    monkeypatch.setattr(
        subject,
        "record_send_attempt",
        lambda *args, **kwargs: events.append("attempt") or {},
    )
    monkeypatch.setattr(
        subject,
        "mark_order_acknowledged",
        lambda *args, **kwargs: events.append("ack") or {},
    )
    monkeypatch.setattr(
        subject,
        "mark_unknown",
        lambda *args, **kwargs: events.append("unknown") or {},
    )
    return events


def _send(monkeypatch, client: FakeClient, **overrides):
    args = dict(
        request=_request(),
        nonce="nonce-test",
        expected_account_fingerprint=PINNED_FINGERPRINT,
        readiness_report=_readiness(),
        same_run_preflight=_preflight(),
        expected_commit_sha=APPROVED_SHA,
        final_confirmation=subject.FINAL_SEND_CONFIRMATION_VALUE,
        repository_root=Path("."),
        timeout_seconds=0.01,
        now=NOW,
        client_factory=lambda: client,
    )
    args.update(overrides)
    return subject.send_exactly_one_live_pilot(**args)


def test_acknowledged_path_calls_place_order_exactly_once(monkeypatch):
    events = _patch_prereqs(monkeypatch)
    client = FakeClient()
    result = _send(monkeypatch, client)

    assert result.status == "ORDER_ACKNOWLEDGED"
    assert result.sent is True
    assert result.acknowledged is True
    assert result.order_id == 77
    assert result.perm_id == 880077
    assert result.account_fingerprint == PINNED_FINGERPRINT
    assert len(client.place_calls) == 1
    assert events == ["journal", "attempt", "ack"]

    order_id, contract, order = client.place_calls[0]
    assert order_id == 77
    assert contract.symbol == "9432"
    assert contract.secType == "STK"
    assert contract.exchange == "TSEJ"
    assert contract.currency == "JPY"
    assert order.action == "BUY"
    assert int(order.totalQuantity) == 100
    assert order.orderType == "LMT"
    assert float(order.lmtPrice) == 400.0
    assert order.tif == "DAY"
    assert order.outsideRth is False
    assert order.account == PINNED_ACCOUNT
    assert order.orderRef == _request().intent_id
    assert order.transmit is True


def test_stop_at_last_possible_point_spends_attempt_without_transport(monkeypatch):
    events = _patch_prereqs(monkeypatch, stop_values=(False, True))
    client = FakeClient()
    result = _send(monkeypatch, client)

    assert result.status == "BLOCKED_STOP_AFTER_ATTEMPT"
    assert result.sent is False
    assert result.recovery_required is True
    assert client.place_calls == []
    assert events == ["journal", "attempt"]


def test_transport_exception_becomes_unknown_and_never_retries(monkeypatch):
    events = _patch_prereqs(monkeypatch)
    client = FakeClient(place_error=RuntimeError("socket outcome ambiguous"))
    result = _send(monkeypatch, client)

    assert result.status == "UNKNOWN"
    assert result.sent is True
    assert result.acknowledged is False
    assert result.recovery_required is True
    assert len(client.place_calls) == 1
    assert events == ["journal", "attempt", "unknown"]


def test_ack_timeout_becomes_unknown_and_never_retries(monkeypatch):
    events = _patch_prereqs(monkeypatch)
    client = FakeClient(ack=False)
    result = _send(monkeypatch, client)

    assert result.status == "UNKNOWN"
    assert len(client.place_calls) == 1
    assert events == ["journal", "attempt", "unknown"]


def test_same_session_account_mismatch_blocks_before_authorization_consumption(monkeypatch):
    events = _patch_prereqs(monkeypatch)
    client = FakeClient(account="U_WRONG")
    result = _send(monkeypatch, client)

    assert result.status == "BLOCKED_ACCOUNT_FINGERPRINT"
    assert result.sent is False
    assert client.place_calls == []
    assert events == []


def test_not_ready_preflight_blocks_before_connection(monkeypatch):
    _patch_prereqs(monkeypatch)
    client = FakeClient()
    with pytest.raises(PermissionError, match="same-run preflight is not ready"):
        _send(monkeypatch, client, same_run_preflight=_preflight(ready=False))
    assert client.connected is False
    assert client.place_calls == []


def test_stale_same_run_preflight_blocks_before_connection(monkeypatch):
    _patch_prereqs(monkeypatch)
    client = FakeClient()
    stale = "2026-09-06T09:59:00+00:00"
    with pytest.raises(PermissionError, match="freshness window"):
        _send(monkeypatch, client, same_run_preflight=_preflight(checked_at=stale))
    assert client.connected is False


def test_stale_readiness_blocks_before_connection(monkeypatch):
    _patch_prereqs(monkeypatch)
    client = FakeClient()
    report = _readiness()
    report["checked_at"] = "2026-09-06T09:59:00+00:00"
    with pytest.raises(PermissionError, match="freshness window"):
        _send(monkeypatch, client, readiness_report=report)
    assert client.connected is False


def test_missing_final_confirmation_blocks_before_connection(monkeypatch):
    _patch_prereqs(monkeypatch)
    client = FakeClient()
    with pytest.raises(PermissionError, match="exact final one-send confirmation"):
        _send(monkeypatch, client, final_confirmation="")
    assert client.connected is False


def test_readiness_price_mismatch_blocks(monkeypatch):
    _patch_prereqs(monkeypatch)
    client = FakeClient()
    bad = _readiness()
    bad["limit_price"] = 399.0
    with pytest.raises(PermissionError, match="limit_price"):
        _send(monkeypatch, client, readiness_report=bad)
    assert client.connected is False


def test_jpy_notional_must_equal_limit_times_quantity(monkeypatch):
    _patch_prereqs(monkeypatch)
    client = FakeClient()
    request = subject.LivePilotSendRequest(
        intent_id="live-pilot:9432:BUY:100:test",
        ticker="9432.T",
        side="BUY",
        quantity=100,
        limit_price=400.0,
        estimated_notional_jpy=39_000.0,
    )
    report = _readiness()
    report["estimated_notional_jpy"] = 39_000.0
    with pytest.raises(PermissionError, match="LIMIT price x quantity"):
        _send(monkeypatch, client, request=request, readiness_report=report)
    assert client.connected is False


def test_absolute_notional_cap_is_rechecked_in_sender(monkeypatch):
    _patch_prereqs(monkeypatch)
    client = FakeClient()
    request = subject.LivePilotSendRequest(
        intent_id="live-pilot:9432:BUY:100:test",
        ticker="9432.T",
        side="BUY",
        quantity=100,
        limit_price=501.0,
        estimated_notional_jpy=50_100.0,
    )
    report = _readiness()
    report["limit_price"] = 501.0
    report["estimated_notional_jpy"] = 50_100.0
    with pytest.raises(PermissionError, match="absolute first-pilot ceiling"):
        _send(monkeypatch, client, request=request, readiness_report=report)
    assert client.connected is False


def test_exact_scope_rejects_wrong_quantity(monkeypatch):
    _patch_prereqs(monkeypatch)
    client = FakeClient()
    request = subject.LivePilotSendRequest(
        intent_id="live-pilot:9432:BUY:99:test",
        ticker="9432.T",
        side="BUY",
        quantity=99,
        limit_price=400.0,
        estimated_notional_jpy=39_600.0,
    )
    with pytest.raises(ValueError, match="exact bounded pilot quantity"):
        _send(monkeypatch, client, request=request)
    assert client.connected is False


def test_source_pin_failure_blocks_before_connection(monkeypatch):
    monkeypatch.setattr(
        subject,
        "audit_live_pilot_source_cutover",
        lambda **kwargs: SimpleNamespace(ready=False),
    )
    monkeypatch.setattr(subject, "live_pilot_stop_is_active", lambda **kwargs: False)
    client = FakeClient()
    with pytest.raises(PermissionError, match="source/PIN"):
        _send(monkeypatch, client)
    assert client.connected is False


def test_module_contains_one_place_order_call_and_no_cancel_transport():
    import inspect

    source = inspect.getsource(subject)
    assert source.count("client.placeOrder(") == 1
    assert "client.cancelOrder(" not in source
    assert "reqGlobalCancel" not in source
