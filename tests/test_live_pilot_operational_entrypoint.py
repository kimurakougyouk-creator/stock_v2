from __future__ import annotations

from pathlib import Path
import os
import subprocess
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
    monkeypatch.setattr(
        subject,
        "audit_live_pilot_source_cutover",
        lambda **kwargs: SimpleNamespace(ready=True),
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


def _postfill_payload() -> dict:
    return {
        "attempted": True,
        "connected": True,
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "executions": [],
        "commissions": [],
        "blocked_reason": None,
        "errors": [],
    }


def test_postfill_promotion_requires_shared_matcher_ready(monkeypatch):
    journal = {
        "state": "ORDER_ACKNOWLEDGED",
        "order_id": 77,
        "perm_id": 880077,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: _postfill_payload()
        if path == subject.DEFAULT_POSTFILL_REPORT
        else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: SimpleNamespace(ready=False, executions=()),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "journal must not advance when shared post-fill matching is not ready"
        ),
    )

    subject._promote_postfill_if_proven(_request())


def test_postfill_promotion_uses_proven_broker_identity_once(monkeypatch):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": 880077,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: _postfill_payload()
        if path == subject.DEFAULT_POSTFILL_REPORT
        else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: SimpleNamespace(
            ready=True,
            executions=(SimpleNamespace(exec_id="0001.test.01"),),
        ),
    )
    calls = []
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    subject._promote_postfill_if_proven(_request())

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (_request().intent_id,)
    assert kwargs["exec_id"] == "0001.test.01"
    assert kwargs["order_id"] == 77
    assert kwargs["perm_id"] == 880077


def test_human_wrapper_has_valid_bash_syntax():
    root = Path(__file__).resolve().parents[1]
    script = root / "live_pilot_operational_once.sh"
    completed = subprocess.run(
        ["bash", "-n", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_human_wrapper_passes_empty_final_confirmation_by_default(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "live_pilot_operational_once.sh"
    fake_root = tmp_path / "runtime"
    (fake_root / ".venv" / "bin").mkdir(parents=True)
    (fake_root / ".venv" / "bin" / "activate").write_text("", encoding="utf-8")
    (fake_root / "scripts").mkdir()
    ensure = fake_root / "scripts" / "ensure_exact_checkout_runtime.sh"
    ensure.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    ensure.chmod(0o755)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"rev-parse\" && \"$2\" == \"HEAD\" ]]; then\n"
        "  printf '%s\\n' \"$LIVE_PILOT_EXPECTED_COMMIT_SHA\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    captured = tmp_path / "python-args.txt"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$WRAPPER_CAPTURE\"\n"
        "exit 2\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env.get('PATH', '')}",
            "AI_ASSET_PLATFORM_ROOT": str(fake_root),
            "LIVE_PILOT_INTENT_ID": _request().intent_id,
            "LIVE_PILOT_TICKER": "9432.T",
            "LIVE_PILOT_SIDE": "BUY",
            "LIVE_PILOT_QUANTITY": "100",
            "LIVE_PILOT_LIMIT_PRICE": "400",
            "LIVE_PILOT_NOTIONAL_JPY": "40000",
            "LIVE_PILOT_NONCE": "nonce-test",
            "LIVE_PILOT_ACCOUNT_FINGERPRINT": FINGERPRINT,
            "LIVE_PILOT_EXPECTED_COMMIT_SHA": SHA,
            "WRAPPER_CAPTURE": str(captured),
        }
    )
    env.pop("LIVE_PILOT_FINAL_CONFIRMATION", None)

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    args = captured.read_text(encoding="utf-8").splitlines()
    flag_index = args.index("--final-confirmation")
    assert args[flag_index + 1] == ""
    assert "--live-readonly-confirmation" in args
    readonly_index = args.index("--live-readonly-confirmation")
    assert args[readonly_index + 1] == "READ_LIVE_ACCOUNT_ONLY"


def test_unknown_recovery_discovers_unique_perm_id_from_readonly_postfill(monkeypatch):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": None,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "0001.test.01",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        }
    ]
    payload["commissions"] = [
        {
            "exec_id": "0001.test.01",
            "commission": 80.0,
            "currency": "JPY",
            "realized_pnl": None,
        }
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    seen = {}

    def fake_match(snapshot, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            ready=True,
            executions=(SimpleNamespace(exec_id="0001.test.01"),),
        )

    monkeypatch.setattr(subject, "match_live_postfill", fake_match)
    calls = []
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    subject._promote_postfill_if_proven(_request())

    assert seen["order_id"] == 77
    assert seen["perm_id"] == 880077
    assert len(calls) == 1
    assert calls[0][1]["perm_id"] == 880077


def test_unknown_recovery_rejects_ambiguous_or_conflicting_broker_identity(monkeypatch):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": None,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: pytest.fail(
            "shared matcher must be unreachable when UNKNOWN broker identity is ambiguous"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "journal must remain UNKNOWN on ambiguous broker identity"
        ),
    )

    ambiguous = _postfill_payload()
    ambiguous["executions"] = [
        {
            "exec_id": "a",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 50.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        },
        {
            "exec_id": "b",
            "order_id": 77,
            "perm_id": 990088,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 50.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        },
    ]
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: ambiguous if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    subject._promote_postfill_if_proven(_request())

    conflicting = _postfill_payload()
    conflicting["executions"] = [
        {
            "exec_id": "a",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "SELL",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        }
    ]
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: conflicting if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    subject._promote_postfill_if_proven(_request())


@pytest.mark.parametrize("bad_order_id", ["77", 77.0, True, 77.5])
def test_recovery_rejects_non_exact_persisted_order_identity(monkeypatch, bad_order_id):
    journal = {
        "state": "UNKNOWN",
        "order_id": bad_order_id,
        "perm_id": None,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: pytest.fail("postfill must not be read for malformed persisted order id"),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail("malformed identity must never be promoted"),
    )

    subject._promote_postfill_if_proven(_request())


@pytest.mark.parametrize("bad_perm_id", ["880077", 880077.0, True, 880077.5])
def test_recovery_rejects_non_exact_persisted_perm_identity(monkeypatch, bad_perm_id):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": bad_perm_id,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: _postfill_payload(),
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: pytest.fail("matcher must not run for malformed perm id"),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail("malformed identity must never be promoted"),
    )

    subject._promote_postfill_if_proven(_request())


def test_send_attempt_recorded_crash_state_can_reconcile_without_sender(monkeypatch):
    journal = {
        "state": "SEND_ATTEMPT_RECORDED",
        "order_id": 77,
        "perm_id": None,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "0001.crash.01",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        }
    ]
    payload["commissions"] = [
        {
            "exec_id": "0001.crash.01",
            "commission": 80.0,
            "currency": "JPY",
            "realized_pnl": None,
        }
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: SimpleNamespace(
            ready=True,
            executions=(SimpleNamespace(exec_id="0001.crash.01"),),
        ),
    )
    calls = []
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    subject._promote_postfill_if_proven(_request())

    assert len(calls) == 1
    assert calls[0][1]["order_id"] == 77
    assert calls[0][1]["perm_id"] == 880077


def test_recovery_rejects_perm_id_reused_by_another_order(monkeypatch):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": None,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        },
        {
            "exec_id": "conflict",
            "order_id": 78,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:01+00:00",
            "account_fingerprint": FINGERPRINT,
        },
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: pytest.fail(
            "shared matcher must be unreachable for contradictory permId evidence"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "contradictory broker identity must not be promoted"
        ),
    )

    subject._promote_postfill_if_proven(_request())


def test_recovery_rejects_non_exact_execution_identity(monkeypatch):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": None,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "bad",
            "order_id": "77",
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        }
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: pytest.fail("matcher must not run on type-invalid identity"),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail("type-invalid identity must not be promoted"),
    )

    subject._promote_postfill_if_proven(_request())


def test_recovery_rejects_order_id_reused_with_another_perm_id(monkeypatch):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": 880077,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        },
        {
            "exec_id": "conflict",
            "order_id": 77,
            "perm_id": 990088,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:01+00:00",
            "account_fingerprint": FINGERPRINT,
        },
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: pytest.fail(
            "matcher must be unreachable when one order_id maps to multiple perm_ids"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "contradictory broker identity must never be promoted"
        ),
    )

    subject._promote_postfill_if_proven(_request())


@pytest.mark.parametrize("bad_perm_id", [None, "990088", 990088.0, True])
def test_recovery_rejects_selected_order_with_malformed_or_wrong_perm_id(
    monkeypatch, bad_perm_id
):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": 880077,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        },
        {
            "exec_id": "bad",
            "order_id": "77",
            "perm_id": bad_perm_id,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:01+00:00",
            "account_fingerprint": FINGERPRINT,
        },
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: pytest.fail(
            "matcher must be unreachable for malformed selected-order identity"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "malformed selected-order identity must never be promoted"
        ),
    )

    subject._promote_postfill_if_proven(_request())


@pytest.mark.parametrize("raw_perm_alias", ["880077", 880077.0])
def test_recovery_rejects_malformed_alias_of_selected_perm_id_on_other_order(
    monkeypatch, raw_perm_alias
):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": 880077,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        },
        {
            "exec_id": "conflict",
            "order_id": 78,
            "perm_id": raw_perm_alias,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:01+00:00",
            "account_fingerprint": FINGERPRINT,
        },
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: pytest.fail(
            "matcher must be unreachable for malformed alias of selected permId"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "malformed alias of broker identity must never be promoted"
        ),
    )

    subject._promote_postfill_if_proven(_request())


@pytest.mark.parametrize("raw_order_alias", ["77", 77.0])
def test_recovery_rejects_malformed_alias_of_selected_order_id_even_with_matching_perm(
    monkeypatch, raw_order_alias
):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": 880077,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        },
        {
            "exec_id": "malformed",
            "order_id": raw_order_alias,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:01+00:00",
            "account_fingerprint": FINGERPRINT,
        },
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: pytest.fail(
            "matcher must be unreachable for malformed alias of selected orderId"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "malformed alias of broker identity must never be promoted"
        ),
    )

    subject._promote_postfill_if_proven(_request())


@pytest.mark.parametrize("bad_order_id,bad_perm_id", [
    ("+77", 880077),
    ("77.0", 880077),
    ("7.7e1", 880077),
    (77, "+880077"),
    (77, "880077.0"),
    (77, "8.80077e5"),
])
def test_recovery_fails_closed_on_any_type_invalid_broker_identity_row(
    monkeypatch, bad_order_id, bad_perm_id
):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": 880077,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        },
        {
            "exec_id": "malformed",
            "order_id": bad_order_id,
            "perm_id": bad_perm_id,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:01+00:00",
            "account_fingerprint": FINGERPRINT,
        },
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "match_live_postfill",
        lambda *args, **kwargs: pytest.fail(
            "matcher must be unreachable when any execution identity row is type-invalid"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "type-invalid broker execution evidence must never be promoted"
        ),
    )

    subject._promote_postfill_if_proven(_request())


def test_recovery_source_cutover_blocks_before_broker_collection(monkeypatch):
    monkeypatch.setattr(subject, "global_send_attempt_recorded", lambda **kwargs: True)
    monkeypatch.setattr(
        subject,
        "audit_live_pilot_source_cutover",
        lambda **kwargs: SimpleNamespace(ready=False),
    )
    monkeypatch.setattr(
        subject,
        "_reconcile_once",
        lambda *args, **kwargs: pytest.fail(
            "recovery broker collection must be unreachable when source audit fails"
        ),
    )
    monkeypatch.setattr(
        subject,
        "send_exactly_one_live_pilot",
        lambda *args, **kwargs: pytest.fail(
            "sender must remain unreachable after campaign marker"
        ),
    )

    result = subject.run_live_pilot_operational_once(_request(), repository_root=Path("/repo"))

    assert result.status == "BLOCKED_SOURCE_CUTOVER"
    assert result.recovery_only is True
    assert result.broker_connection_used is False
    assert result.order_transport_called is False


def test_postfill_proven_still_revalidates_fresh_execution_identity(monkeypatch):
    journal = {
        "state": "POSTFILL_PROVEN",
        "order_id": 77,
        "perm_id": 880077,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "malformed",
            "order_id": "+77",
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        }
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "already-promoted journal must not be rewritten"
        ),
    )

    subject._promote_postfill_if_proven(_request())


def test_postfill_proven_accepts_only_exact_int_fresh_execution_identity(monkeypatch):
    journal = {
        "state": "POSTFILL_PROVEN",
        "order_id": 77,
        "perm_id": 880077,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 100.0,
            "price": 402.0,
            "time": "2026-09-21T00:00:00+00:00",
            "account_fingerprint": FINGERPRINT,
        }
    ]
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "_load_json",
        lambda path: payload if path == subject.DEFAULT_POSTFILL_REPORT else None,
    )
    monkeypatch.setattr(
        subject,
        "mark_postfill_proven",
        lambda *args, **kwargs: pytest.fail(
            "already-promoted journal must not be rewritten"
        ),
    )

    subject._promote_postfill_if_proven(_request())
