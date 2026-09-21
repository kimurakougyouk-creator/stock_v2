from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_asset_platform.execution.live_pilot_operational_entrypoint as subject
from ai_asset_platform.execution.live_pilot_single_send import LivePilotSendResult


FINGERPRINT = "a" * 64
SHA = "b" * 40


def _request(**overrides) -> subject.LivePilotOperationalRequest:
    data = {
        "intent_id": "live-pilot:9432:BUY:100:test",
        "ticker": "9432.T",
        "side": "BUY",
        "quantity": 100,
        "limit_price": 400.0,
        "estimated_notional_jpy": 40_000.0,
        "nonce": "nonce-test",
        "expected_account_fingerprint": FINGERPRINT,
        "expected_commit_sha": SHA,
        "final_confirmation": "FINAL_CONFIRMATION_TEST",
        "live_readonly_confirmation": subject.LIVE_READONLY_CONFIRMATION_VALUE,
    }
    data.update(overrides)
    return subject.LivePilotOperationalRequest(**data)


def _result(
    *,
    status: str = "RECOVERY_REQUIRED",
    recovery_only: bool = True,
    order_transport_called: bool = False,
) -> subject.LivePilotOperationalResult:
    return subject.LivePilotOperationalResult(
        status=status,
        checked_at="2026-09-21T00:00:00+00:00",
        recovery_only=recovery_only,
        preflight_ready=False,
        send_status=None,
        completion_status="BLOCKED",
        complete=False,
        blockers=("blocked",),
        broker_connection_used=True,
        order_transport_called=order_transport_called,
    )


def test_missing_readonly_confirmation_blocks_before_marker_or_broker(monkeypatch):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: pytest.fail("marker lookup must not run"),
    )
    monkeypatch.setattr(
        subject,
        "_collect_presend_readonly_evidence",
        lambda request: pytest.fail("broker collection must not run"),
    )

    result = subject.run_live_pilot_operational_once(
        _request(live_readonly_confirmation="WRONG")
    )

    assert result.status == "BLOCKED_READONLY_CONFIRMATION"
    assert result.broker_connection_used is False
    assert result.order_transport_called is False
    assert result.automatic_retry_allowed is False
    assert result.automatic_cancel_allowed is False
    assert result.automatic_modify_allowed is False
    assert result.automatic_flatten_allowed is False
    assert result.automatic_close_allowed is False


def test_existing_campaign_marker_forces_recovery_only_and_sender_is_unreachable(
    monkeypatch,
):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        subject,
        "send_exactly_one_live_pilot",
        lambda *args, **kwargs: pytest.fail("sender must be unreachable after marker"),
    )
    calls = []

    def fake_reconcile(request, *, send_status, order_transport_called):
        calls.append((request.intent_id, send_status, order_transport_called))
        return _result()

    monkeypatch.setattr(subject, "_reconcile_once", fake_reconcile)

    result = subject.run_live_pilot_operational_once(_request())

    assert result.status == "RECOVERY_REQUIRED"
    assert result.recovery_only is True
    assert result.order_transport_called is False
    assert calls == [("live-pilot:9432:BUY:100:test", None, False)]


def test_blocked_same_run_preflight_never_reaches_sender(monkeypatch):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        subject,
        "_collect_presend_readonly_evidence",
        lambda request: None,
    )
    preflight = SimpleNamespace(
        ready=False,
        blockers=("same-run evidence is stale",),
    )
    monkeypatch.setattr(
        subject,
        "_evaluate_and_persist_preflight",
        lambda request: ({"status": "BLOCKED"}, preflight),
    )
    monkeypatch.setattr(
        subject,
        "send_exactly_one_live_pilot",
        lambda *args, **kwargs: pytest.fail("sender must not run"),
    )

    result = subject.run_live_pilot_operational_once(_request())

    assert result.status == "BLOCKED_PREFLIGHT"
    assert result.preflight_ready is False
    assert result.order_transport_called is False
    assert result.blockers == ("same-run evidence is stale",)


def test_ready_path_delegates_to_existing_sender_exactly_once(monkeypatch):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        subject,
        "_collect_presend_readonly_evidence",
        lambda request: None,
    )
    preflight = SimpleNamespace(ready=True, blockers=())
    readiness = {
        "status": "READY_FOR_ONE_OPERATIONAL_PILOT",
        "operational_pilot_ready": True,
    }
    monkeypatch.setattr(
        subject,
        "_evaluate_and_persist_preflight",
        lambda request: (readiness, preflight),
    )

    calls = []

    def fake_send(request, **kwargs):
        calls.append((request, kwargs))
        return LivePilotSendResult(
            status="BLOCKED_NOT_CONNECTED",
            sent=False,
            acknowledged=False,
            order_id=None,
            perm_id=None,
            endpoint_port=4001,
            account_fingerprint=None,
            broker_status=None,
            recovery_required=False,
            message="not connected",
        )

    monkeypatch.setattr(subject, "send_exactly_one_live_pilot", fake_send)

    result = subject.run_live_pilot_operational_once(
        _request(),
        repository_root=Path("/repo"),
    )

    assert len(calls) == 1
    sent_request, kwargs = calls[0]
    assert sent_request.intent_id == _request().intent_id
    assert sent_request.ticker == "9432.T"
    assert sent_request.quantity == 100
    assert kwargs["nonce"] == "nonce-test"
    assert kwargs["expected_account_fingerprint"] == FINGERPRINT
    assert kwargs["expected_commit_sha"] == SHA
    assert kwargs["repository_root"] == Path("/repo")
    assert result.status == "BLOCKED_NOT_CONNECTED"
    assert result.order_transport_called is False


def test_irreversible_attempt_switches_to_one_readonly_reconciliation_pass(
    monkeypatch,
):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        subject,
        "_collect_presend_readonly_evidence",
        lambda request: None,
    )
    preflight = SimpleNamespace(ready=True, blockers=())
    monkeypatch.setattr(
        subject,
        "_evaluate_and_persist_preflight",
        lambda request: ({"status": "READY_FOR_ONE_OPERATIONAL_PILOT"}, preflight),
    )

    send_calls = []

    def fake_send(*args, **kwargs):
        send_calls.append(1)
        return LivePilotSendResult(
            status="UNKNOWN",
            sent=True,
            acknowledged=False,
            order_id=77,
            perm_id=None,
            endpoint_port=4001,
            account_fingerprint=FINGERPRINT,
            broker_status=None,
            recovery_required=True,
            message="unknown; no retry",
        )

    monkeypatch.setattr(subject, "send_exactly_one_live_pilot", fake_send)
    reconcile_calls = []

    def fake_reconcile(request, *, send_status, order_transport_called):
        reconcile_calls.append((send_status, order_transport_called))
        return _result(
            status="RECOVERY_REQUIRED",
            recovery_only=True,
            order_transport_called=True,
        )

    monkeypatch.setattr(subject, "_reconcile_once", fake_reconcile)

    result = subject.run_live_pilot_operational_once(_request())

    assert len(send_calls) == 1
    assert reconcile_calls == [("UNKNOWN", True)]
    assert result.recovery_only is True
    assert result.order_transport_called is True
    assert result.automatic_retry_allowed is False


def test_operational_result_persists_no_future_send_authorization(tmp_path):
    path = tmp_path / "operational.json"
    subject.persist_operational_result(
        _result(status="COMPLETE"),
        report_path=path,
    )

    payload = subject._load_json(path)
    assert payload is not None
    assert payload["live_execution_authorized_by_this_report"] is False
    assert payload["automatic_retry_allowed"] is False
    assert payload["automatic_cancel_allowed"] is False
    assert payload["automatic_modify_allowed"] is False
    assert payload["automatic_flatten_allowed"] is False
    assert payload["automatic_close_allowed"] is False
