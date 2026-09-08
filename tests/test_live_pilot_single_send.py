from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def _preflight(
    *,
    ready: bool = True,
    checked_at: str = CHECKED_AT,
    expected_account_fingerprint: str | None = None,
) -> LivePilotSameRunPreflight:
    return LivePilotSameRunPreflight(
        status="READY_FOR_OPERATOR_AUTHORIZATION" if ready else "BLOCKED",
        checked_at=checked_at,
        blockers=() if ready else ("blocked",),
        ticker="9432.T",
        account_fingerprint_match=ready,
        expected_account_fingerprint=(
            expected_account_fingerprint
            if expected_account_fingerprint is not None
            else (PINNED_FINGERPRINT if ready else None)
        ),
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


def _patch_prereqs(
    monkeypatch,
    *,
    stop_values=(False, False),
    authorization_expires_at=None,
):
    expires_at = (
        authorization_expires_at
        if authorization_expires_at is not None
        else (NOW + timedelta(minutes=10)).isoformat(timespec="seconds")
    )
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
            "expires_at": expires_at,
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


def test_preflight_for_different_account_cannot_be_reused_for_this_send(monkeypatch):
    """Codex P1: a genuine preflight for account A must not authorize a send

    pinned to account B merely because account_fingerprint_match is True on
    that (unrelated) preflight record.
    """
    events = _patch_prereqs(monkeypatch)
    client = FakeClient()
    other_fingerprint = hashlib.sha256(b"U_OTHER_ACCOUNT").hexdigest()
    preflight = _preflight(expected_account_fingerprint=other_fingerprint)
    with pytest.raises(PermissionError, match="pinned account fingerprint"):
        _send(monkeypatch, client, same_run_preflight=preflight)
    assert client.connected is False
    assert events == []


def test_final_freshness_check_rereads_the_clock_not_a_fixed_now(monkeypatch):
    """Codex P1: the post-connection freshness re-check must observe real

    elapsed time. A caller-supplied clock callable that advances past the
    freshness window between the two checks must still block the send, even
    though the first (pre-connection) check passed.
    """
    events = _patch_prereqs(monkeypatch)
    client = FakeClient()
    calls = {"count": 0}

    def advancing_clock() -> datetime:
        calls["count"] += 1
        if calls["count"] == 1:
            return NOW
        return NOW + timedelta(seconds=subject.FINAL_EVIDENCE_MAX_AGE_SECONDS + 1)

    with pytest.raises(PermissionError, match="freshness window"):
        _send(monkeypatch, client, now=advancing_clock)
    assert calls["count"] >= 2
    assert client.place_calls == []
    assert events == []


def test_stale_evidence_after_durable_attempt_recording_blocks_transport(monkeypatch):
    """Codex P1 (round 2): even after the post-connection freshness re-check

    passes, the fsync-backed authorization/journal/attempt writes that follow
    it can themselves stall. If evidence has aged past its window by the time
    those durable writes finish, transport must still be blocked -- with the
    attempt already (and irreversibly) spent -- rather than transmitting on
    stale evidence merely because no clock was read again before placeOrder.
    """
    events = _patch_prereqs(monkeypatch)
    client = FakeClient()
    calls = {"count": 0}

    def advancing_clock() -> datetime:
        calls["count"] += 1
        if calls["count"] <= 2:
            return NOW
        return NOW + timedelta(seconds=subject.FINAL_EVIDENCE_MAX_AGE_SECONDS + 1)

    result = _send(monkeypatch, client, now=advancing_clock)

    assert result.status == "BLOCKED_STALE_AFTER_ATTEMPT"
    assert result.sent is False
    assert result.recovery_required is True
    assert calls["count"] >= 3
    assert client.place_calls == []
    # The irreversible attempt marker must already have been recorded before
    # this check runs -- it is not skipped/rolled back just because transport
    # is subsequently blocked.
    assert events == ["journal", "attempt"]


def test_expired_authorization_after_durable_attempt_recording_blocks_transport(monkeypatch):
    """Codex P1 (round 5): the post-attempt re-check must also catch an

    operator authorization whose own (independent, possibly shorter) TTL
    elapsed while the durable writes ran, even when the readiness/preflight
    30-second freshness window has not yet been exceeded.
    """
    short_lived_expiry = (NOW + timedelta(seconds=5)).isoformat(timespec="seconds")
    events = _patch_prereqs(monkeypatch, authorization_expires_at=short_lived_expiry)
    client = FakeClient()
    calls = {"count": 0}

    def advancing_clock() -> datetime:
        calls["count"] += 1
        if calls["count"] <= 2:
            return NOW
        # Past the 5-second authorization expiry, but still well inside the
        # 30-second readiness/preflight freshness window.
        return NOW + timedelta(seconds=10)

    result = _send(monkeypatch, client, now=advancing_clock)

    assert result.status == "BLOCKED_STALE_AFTER_ATTEMPT"
    assert result.sent is False
    assert result.recovery_required is True
    assert client.place_calls == []
    assert events == ["journal", "attempt"]


def test_fixed_now_still_works_for_simple_deterministic_tests(monkeypatch):
    events = _patch_prereqs(monkeypatch)
    client = FakeClient()
    result = _send(monkeypatch, client, now=NOW)
    assert result.status == "ORDER_ACKNOWLEDGED"
    assert events == ["journal", "attempt", "ack"]


def test_inactive_open_order_status_does_not_falsely_acknowledge():
    """Codex P1: openOrder must not treat a non-accepted status (e.g.

    Inactive) as acknowledgement merely because permId is already positive.
    """
    client = subject._LivePilotClient()
    client.watched_order_id = 77
    client.watched_account = PINNED_ACCOUNT

    inactive_order = SimpleNamespace(account=PINNED_ACCOUNT, permId=880077)
    inactive_state = SimpleNamespace(status="Inactive")
    client.openOrder(77, object(), inactive_order, inactive_state)

    assert client.ack_ready.is_set() is True
    assert client.ack_perm_id is None
    assert client.order_error is not None
    assert "Inactive" in client.order_error


def test_accepted_open_order_status_still_acknowledges():
    client = subject._LivePilotClient()
    client.watched_order_id = 77
    client.watched_account = PINNED_ACCOUNT

    order = SimpleNamespace(account=PINNED_ACCOUNT, permId=880077)
    state = SimpleNamespace(status="Submitted")
    client.openOrder(77, object(), order, state)

    assert client.ack_ready.is_set() is True
    assert client.ack_perm_id == 880077
    assert client.order_error is None


def _client() -> "subject._LivePilotClient":
    client = subject._LivePilotClient()
    client.watched_order_id = 77
    client.watched_account = PINNED_ACCOUNT
    return client


def test_pending_submit_alone_is_nonterminal_and_never_wakes_the_waiter():
    """PM P1: PendingSubmit is a genuine interim state, not a rejection --

    it must never set order_error or ack_ready by itself (this is what the
    caller's overall timeout, not this callback, must eventually resolve).
    """
    client = _client()
    order = SimpleNamespace(account=PINNED_ACCOUNT, permId=0)
    state = SimpleNamespace(status="PendingSubmit")
    client.openOrder(77, object(), order, state)

    assert client.ack_ready.is_set() is False
    assert client.order_error is None
    assert client.ack_perm_id is None
    assert client.broker_status == "PendingSubmit"


def test_pending_submit_then_pre_submitted_acknowledges():
    client = _client()
    client.openOrder(
        77, object(), SimpleNamespace(account=PINNED_ACCOUNT, permId=0), SimpleNamespace(status="PendingSubmit")
    )
    assert client.ack_ready.is_set() is False

    client.openOrder(
        77,
        object(),
        SimpleNamespace(account=PINNED_ACCOUNT, permId=880077),
        SimpleNamespace(status="PreSubmitted"),
    )
    assert client.ack_ready.is_set() is True
    assert client.ack_perm_id == 880077
    assert client.order_error is None


def test_pending_submit_then_submitted_acknowledges():
    client = _client()
    client.openOrder(
        77, object(), SimpleNamespace(account=PINNED_ACCOUNT, permId=0), SimpleNamespace(status="PendingSubmit")
    )
    client.openOrder(
        77,
        object(),
        SimpleNamespace(account=PINNED_ACCOUNT, permId=880077),
        SimpleNamespace(status="Submitted"),
    )
    assert client.ack_ready.is_set() is True
    assert client.ack_perm_id == 880077
    assert client.order_error is None


def test_pending_submit_then_inactive_fails_closed_as_definitive_rejection():
    client = _client()
    client.openOrder(
        77, object(), SimpleNamespace(account=PINNED_ACCOUNT, permId=0), SimpleNamespace(status="PendingSubmit")
    )
    assert client.ack_ready.is_set() is False

    client.openOrder(
        77,
        object(),
        SimpleNamespace(account=PINNED_ACCOUNT, permId=0),
        SimpleNamespace(status="Inactive"),
    )
    assert client.ack_ready.is_set() is True
    assert client.ack_perm_id is None
    assert client.order_error is not None
    assert "Inactive" in client.order_error


def test_duplicate_and_interleaved_pending_submit_callbacks_stay_harmless():
    """Duplicate/interleaved PendingSubmit callbacks (openOrder and

    orderStatus both firing repeatedly) must remain nonterminal and never
    accumulate into a false ack or a false error.
    """
    client = _client()
    for _ in range(3):
        client.openOrder(
            77, object(), SimpleNamespace(account=PINNED_ACCOUNT, permId=0), SimpleNamespace(status="PendingSubmit")
        )
        client.orderStatus(77, "PendingSubmit", 0.0, 100.0, 0.0, 0, 0, 0.0, 0, "", 0.0)

    assert client.ack_ready.is_set() is False
    assert client.order_error is None
    assert client.ack_perm_id is None

    # A later genuine acknowledgement still works normally afterward.
    client.openOrder(
        77,
        object(),
        SimpleNamespace(account=PINNED_ACCOUNT, permId=880077),
        SimpleNamespace(status="Submitted"),
    )
    assert client.ack_ready.is_set() is True
    assert client.ack_perm_id == 880077


def test_order_status_pending_submit_then_submitted_acknowledges():
    client = _client()
    client.orderStatus(77, "PendingSubmit", 0.0, 100.0, 0.0, 0, 0, 0.0, 0, "", 0.0)
    assert client.ack_ready.is_set() is False
    assert client.order_error is None

    client.orderStatus(77, "Submitted", 0.0, 100.0, 0.0, 880077, 0, 0.0, 0, "", 0.0)
    assert client.ack_ready.is_set() is True
    assert client.ack_perm_id == 880077
    assert client.order_error is None


def test_order_status_terminal_rejection_wakes_the_waiter():
    """PM audit: orderStatus previously silently ignored Cancelled/

    ApiCancelled/Inactive/PendingCancel, relying solely on openOrder/error to
    ever wake the waiter. A definitive rejection must not be able to hang
    until the full timeout when orderStatus alone reports it.
    """
    for bad_status in ("Cancelled", "ApiCancelled", "Inactive", "PendingCancel"):
        client = _client()
        client.orderStatus(77, bad_status, 0.0, 100.0, 0.0, 0, 0, 0.0, 0, "", 0.0)
        assert client.ack_ready.is_set() is True, bad_status
        assert client.ack_perm_id is None, bad_status
        assert client.order_error is not None and bad_status in client.order_error, bad_status


def test_order_status_partial_and_full_fill_both_acknowledge():
    """A partial fill (filled < remaining) reported via a Submitted status,

    and a completed fill reported via Filled, must both acknowledge -- fill
    quantity is proven later by post-fill reconciliation, not this ack wait.
    """
    partial = _client()
    partial.orderStatus(77, "Submitted", 40.0, 60.0, 400.0, 880077, 0, 0.0, 0, "", 0.0)
    assert partial.ack_ready.is_set() is True
    assert partial.ack_perm_id == 880077

    full = _client()
    full.orderStatus(77, "Filled", 100.0, 0.0, 400.0, 880077, 0, 0.0, 0, "", 0.0)
    assert full.ack_ready.is_set() is True
    assert full.ack_perm_id == 880077


def test_error_callback_after_pending_submit_wakes_the_waiter():
    """A definitive broker error for the watched order must wake the waiter

    even while the order is still sitting in PendingSubmit.
    """
    client = _client()
    client.openOrder(
        77, object(), SimpleNamespace(account=PINNED_ACCOUNT, permId=0), SimpleNamespace(status="PendingSubmit")
    )
    assert client.ack_ready.is_set() is False

    client.error(77, 201, "Order rejected - reason")
    assert client.ack_ready.is_set() is True
    assert client.order_error is not None
    assert "201" in client.order_error


def test_duplicate_accepted_callbacks_after_ack_do_not_change_the_outcome():
    """A duplicate/late accepted callback arriving after the waiter has

    already been woken must not flip a successful ack to an error or vice
    versa -- ack_ready being an Event, re-setting it is a no-op, and the
    caller only reads state once after its single wait().
    """
    client = _client()
    client.openOrder(
        77,
        object(),
        SimpleNamespace(account=PINNED_ACCOUNT, permId=880077),
        SimpleNamespace(status="Submitted"),
    )
    assert client.ack_ready.is_set() is True
    assert client.ack_perm_id == 880077

    # A duplicate/late orderStatus for the same order must not disturb the
    # already-recorded successful acknowledgement.
    client.orderStatus(77, "Submitted", 100.0, 0.0, 400.0, 880077, 0, 0.0, 0, "", 0.0)
    assert client.ack_perm_id == 880077
    assert client.order_error is None


def test_stale_reordered_pending_submit_after_ack_does_not_disturb_the_outcome():
    """A stale/out-of-order PendingSubmit callback arriving after a genuine

    acknowledgement (e.g. delivered out of order over the socket) must not
    downgrade broker_status or otherwise disturb the already-proven ack.
    """
    client = _client()
    client.openOrder(
        77,
        object(),
        SimpleNamespace(account=PINNED_ACCOUNT, permId=880077),
        SimpleNamespace(status="Submitted"),
    )
    assert client.ack_ready.is_set() is True
    assert client.broker_status == "Submitted"

    client.openOrder(
        77, object(), SimpleNamespace(account=PINNED_ACCOUNT, permId=0), SimpleNamespace(status="PendingSubmit")
    )
    assert client.ack_ready.is_set() is True
    assert client.ack_perm_id == 880077
    assert client.order_error is None
    assert client.broker_status == "Submitted"
