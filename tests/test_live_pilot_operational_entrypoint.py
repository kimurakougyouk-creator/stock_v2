from __future__ import annotations

from datetime import datetime, timezone
import json
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


def _install_wrapper_probe_module(fake_root: Path) -> None:
    module_dir = fake_root / "src" / "ai_asset_platform" / "execution"
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir.parent / "__init__.py").write_text("", encoding="utf-8")
    (module_dir / "__init__.py").write_text("", encoding="utf-8")
    (module_dir / "live_pilot_operational_entrypoint.py").write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['WRAPPER_CAPTURE']).write_text("
        "json.dumps(sys.argv), encoding='utf-8')\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _active_authorization_binding(monkeypatch):
    monkeypatch.setattr(
        subject,
        "load_live_pilot_authorization_binding",
        lambda **kwargs: {"endpoint_port": 4001},
    )


def _bound_journal(**overrides) -> dict:
    data = {
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    data.update(overrides)
    return data


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
        lambda request, *, authorized_endpoint_port: pytest.fail(
            "broker collection must not run"
        ),
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
        "load_send_journal",
        lambda *args, **kwargs: _bound_journal(),
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


def test_unreadable_journal_at_recovery_dispatch_blocks_before_source_or_broker(
    monkeypatch,
):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        subject,
        "load_send_journal",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            json.JSONDecodeError("truncated journal", "{", 1)
        ),
    )
    monkeypatch.setattr(
        subject,
        "audit_live_pilot_source_cutover",
        lambda **kwargs: pytest.fail(
            "source audit must be unreachable when durable journal is unreadable"
        ),
    )
    monkeypatch.setattr(
        subject,
        "_reconcile_once",
        lambda *args, **kwargs: pytest.fail(
            "recovery dispatch must block before reconciliation"
        ),
    )
    monkeypatch.setattr(
        subject,
        "send_exactly_one_live_pilot",
        lambda *args, **kwargs: pytest.fail(
            "sender must remain unreachable after campaign marker"
        ),
    )

    result = subject.run_live_pilot_operational_once(_request())

    assert result.status == "BLOCKED_TERMINAL_EVIDENCE"
    assert result.recovery_only is True
    assert result.complete is False
    assert result.broker_connection_used is False
    assert result.order_transport_called is False
    assert any("journal is unreadable" in item for item in result.blockers)


def test_blocked_same_run_preflight_never_reaches_sender(monkeypatch):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        subject,
        "_collect_presend_readonly_evidence",
        lambda request, *, authorized_endpoint_port: None,
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


def test_invalid_active_authorization_blocks_before_presend_broker(monkeypatch):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        subject,
        "load_live_pilot_authorization_binding",
        lambda **kwargs: (_ for _ in ()).throw(
            PermissionError("authorization nonce has expired")
        ),
    )
    monkeypatch.setattr(
        subject,
        "_collect_presend_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "broker collection must be unreachable for invalid authorization"
        ),
    )

    result = subject.run_live_pilot_operational_once(_request())

    assert result.status == "BLOCKED_AUTHORIZATION_BINDING"
    assert result.broker_connection_used is False
    assert result.order_transport_called is False
    assert "authorization nonce has expired" in result.blockers[0]


def test_presend_collection_uses_active_authorized_endpoint(monkeypatch):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        subject,
        "load_live_pilot_authorization_binding",
        lambda **kwargs: {"endpoint_port": 7496},
    )
    seen = []

    def fake_collect(request, *, authorized_endpoint_port):
        seen.append(authorized_endpoint_port)

    monkeypatch.setattr(subject, "_collect_presend_readonly_evidence", fake_collect)
    monkeypatch.setattr(
        subject,
        "_evaluate_and_persist_preflight",
        lambda request: (
            {"status": "BLOCKED"},
            SimpleNamespace(ready=False, blockers=("stop after collection",)),
        ),
    )

    result = subject.run_live_pilot_operational_once(_request())

    assert seen == [7496]
    assert result.status == "BLOCKED_PREFLIGHT"


def test_ready_path_delegates_to_existing_sender_exactly_once(monkeypatch):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        subject,
        "_collect_presend_readonly_evidence",
        lambda request, *, authorized_endpoint_port: None,
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
        lambda request, *, authorized_endpoint_port: None,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
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
    (fake_root / ".venv" / "lib" / "python3.13" / "site-packages").mkdir(parents=True)
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
        "if [[ \"$1\" == \"status\" && \"$2\" == \"--porcelain=v1\" && \"$3\" == \"--untracked-files=all\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"ls-files\" && \"$2\" == \"-v\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"ls-files\" && \"$2\" == \"--others\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    captured = tmp_path / "python-args.txt"
    (fake_root / ".venv" / "bin" / "python").symlink_to("/usr/bin/python3")
    _install_wrapper_probe_module(fake_root)

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
    args = json.loads(captured.read_text(encoding="utf-8"))
    flag_index = args.index("--final-confirmation")
    assert args[flag_index + 1] == ""
    assert "--live-readonly-confirmation" in args
    readonly_index = args.index("--live-readonly-confirmation")
    assert args[readonly_index + 1] == "READ_LIVE_ACCOUNT_ONLY"


def test_human_wrapper_blocks_untracked_source_before_python_launch(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "live_pilot_operational_once.sh"
    fake_root = tmp_path / "runtime"
    (fake_root / ".venv" / "bin").mkdir(parents=True)
    (fake_root / ".venv" / "lib" / "python3.13" / "site-packages").mkdir(parents=True)
    (fake_root / "scripts").mkdir()
    ensure_marker = tmp_path / "ensure-ran.txt"
    ensure = fake_root / "scripts" / "ensure_exact_checkout_runtime.sh"
    ensure.write_text(
        "#!/usr/bin/env bash\nprintf 'ran\\n' > \"$ENSURE_MARKER\"\n",
        encoding="utf-8",
    )
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
        "if [[ \"$1\" == \"status\" && \"$2\" == \"--porcelain=v1\" && \"$3\" == \"--untracked-files=all\" ]]; then\n"
        "  printf '%s\\n' '?? src/sitecustomize.py'\n"
        "  exit 0\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    python_marker = tmp_path / "python-ran.txt"
    (fake_root / ".venv" / "bin" / "python").symlink_to("/usr/bin/python3")
    _install_wrapper_probe_module(fake_root)

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
            "ENSURE_MARKER": str(ensure_marker),
            "PYTHON_MARKER": str(python_marker),
        }
    )

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "tracked or untracked audited source changes" in completed.stdout
    assert ensure_marker.exists() is False
    assert python_marker.exists() is False


def test_human_wrapper_blocks_ignored_importable_before_python_launch(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "live_pilot_operational_once.sh"
    fake_root = tmp_path / "runtime"
    (fake_root / ".venv" / "bin").mkdir(parents=True)
    (fake_root / ".venv" / "lib" / "python3.13" / "site-packages").mkdir(parents=True)
    (fake_root / "scripts").mkdir()
    ensure_marker = tmp_path / "ensure-ran.txt"
    ensure = fake_root / "scripts" / "ensure_exact_checkout_runtime.sh"
    ensure.write_text(
        "#!/usr/bin/env bash\nprintf 'ran\\n' > \"$ENSURE_MARKER\"\n",
        encoding="utf-8",
    )
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
        "if [[ \"$1\" == \"status\" && \"$2\" == \"--porcelain=v1\" && \"$3\" == \"--untracked-files=all\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"ls-files\" && \"$2\" == \"-v\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"ls-files\" && \"$2\" == \"--others\" ]]; then\n"
        "  printf '%s\\n' 'src/sitecustomize.pyc'\n"
        "  exit 0\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    python_marker = tmp_path / "python-ran.txt"
    (fake_root / ".venv" / "bin" / "python").symlink_to("/usr/bin/python3")
    _install_wrapper_probe_module(fake_root)

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
            "ENSURE_MARKER": str(ensure_marker),
            "PYTHON_MARKER": str(python_marker),
        }
    )

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "ignored importable artifact" in completed.stdout
    assert ensure_marker.exists() is False
    assert python_marker.exists() is False


def test_human_wrapper_blocks_ignored_package_symlink_before_python_launch(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "live_pilot_operational_once.sh"
    fake_root = tmp_path / "runtime"
    (fake_root / ".venv" / "bin").mkdir(parents=True)
    (fake_root / ".venv" / "lib" / "python3.13" / "site-packages").mkdir(parents=True)
    (fake_root / "scripts").mkdir()
    ensure_marker = tmp_path / "ensure-ran.txt"
    ensure = fake_root / "scripts" / "ensure_exact_checkout_runtime.sh"
    ensure.write_text(
        "#!/usr/bin/env bash\nprintf 'ran\\n' > \"$ENSURE_MARKER\"\n",
        encoding="utf-8",
    )
    ensure.chmod(0o755)

    shadow = (
        fake_root
        / "src"
        / "ai_asset_platform"
        / "execution"
        / "live_pilot_operational_entrypoint"
    )
    shadow.parent.mkdir(parents=True)
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "__init__.py").write_text(
        "raise RuntimeError('must not execute')\n",
        encoding="utf-8",
    )
    shadow.symlink_to(payload, target_is_directory=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"rev-parse\" && \"$2\" == \"HEAD\" ]]; then\n"
        "  printf '%s\\n' \"$LIVE_PILOT_EXPECTED_COMMIT_SHA\"\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"status\" && \"$2\" == \"--porcelain=v1\" && \"$3\" == \"--untracked-files=all\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"ls-files\" && \"$2\" == \"-v\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"ls-files\" && \"$2\" == \"--others\" ]]; then\n"
        "  printf '%s\\n' 'src/ai_asset_platform/execution/live_pilot_operational_entrypoint'\n"
        "  exit 0\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    python_marker = tmp_path / "python-ran.txt"
    (fake_root / ".venv" / "bin" / "python").symlink_to("/usr/bin/python3")
    _install_wrapper_probe_module(fake_root)

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
            "ENSURE_MARKER": str(ensure_marker),
            "PYTHON_MARKER": str(python_marker),
        }
    )

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "ignored importable artifact, package, or symlink" in completed.stdout
    assert ensure_marker.exists() is False
    assert python_marker.exists() is False


def test_human_wrapper_blocks_index_hidden_source_before_python_launch(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "live_pilot_operational_once.sh"
    fake_root = tmp_path / "runtime"
    (fake_root / ".venv" / "bin").mkdir(parents=True)
    (fake_root / ".venv" / "lib" / "python3.13" / "site-packages").mkdir(parents=True)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"rev-parse\" && \"$2\" == \"HEAD\" ]]; then\n"
        "  printf '%s\\n' \"$LIVE_PILOT_EXPECTED_COMMIT_SHA\"\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"status\" && \"$2\" == \"--porcelain=v1\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"ls-files\" && \"$2\" == \"-v\" ]]; then\n"
        "  printf '%s\\n' 'h src/ai_asset_platform/execution/live_pilot_operational_entrypoint.py'\n"
        "  exit 0\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    python_marker = tmp_path / "python-ran.txt"
    (fake_root / ".venv" / "bin" / "python").symlink_to("/usr/bin/python3")
    _install_wrapper_probe_module(fake_root)

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
            "PYTHON_MARKER": str(python_marker),
        }
    )

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "assume-unchanged or skip-worktree" in completed.stdout
    assert python_marker.exists() is False


def test_human_wrapper_never_sources_venv_activate(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "live_pilot_operational_once.sh"
    fake_root = tmp_path / "runtime"
    (fake_root / ".venv" / "bin").mkdir(parents=True)
    (fake_root / ".venv" / "lib" / "python3.13" / "site-packages").mkdir(parents=True)

    activate_marker = tmp_path / "activate-ran.txt"
    (fake_root / ".venv" / "bin" / "activate").write_text(
        f"printf 'ran\\n' > '{activate_marker}'\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"rev-parse\" && \"$2\" == \"HEAD\" ]]; then\n"
        "  printf '%s\\n' \"$LIVE_PILOT_EXPECTED_COMMIT_SHA\"\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"status\" && \"$2\" == \"--porcelain=v1\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"ls-files\" && \"$2\" == \"-v\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"ls-files\" && \"$2\" == \"--others\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    captured = tmp_path / "python-args.txt"
    (fake_root / ".venv" / "bin" / "python").symlink_to("/usr/bin/python3")
    _install_wrapper_probe_module(fake_root)

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

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert activate_marker.exists() is False
    args = json.loads(captured.read_text(encoding="utf-8"))
    assert "--intent-id" in args
    source = script.read_text(encoding="utf-8")
    assert '"$TRUSTED_PYTHON_REAL" -I -P -S -c "$PYTHON_BOOTSTRAP"' in source


def test_human_wrapper_rejects_malicious_venv_python_before_execution(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "live_pilot_operational_once.sh"
    fake_root = tmp_path / "runtime"
    (fake_root / ".venv" / "bin").mkdir(parents=True)

    marker = tmp_path / "malicious-python-ran.txt"
    malicious = tmp_path / "malicious-python"
    malicious.write_text(
        f"#!/usr/bin/env bash\nprintf 'ran\\n' > '{marker}'\nexit 0\n",
        encoding="utf-8",
    )
    malicious.chmod(0o755)
    (fake_root / ".venv" / "bin" / "python").symlink_to(malicious)

    env = os.environ.copy()
    env["AI_ASSET_PLATFORM_ROOT"] = str(fake_root)

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "approved system Python path" in completed.stdout
    assert marker.exists() is False


def test_unknown_recovery_discovers_unique_perm_id_from_readonly_postfill(monkeypatch):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": None,
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "0001.test.01",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
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
            "exec_id": "other-client-same-order-id",
            "order_id": 77,
            "perm_id": 990088,
            "client_id": 999,
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
    assert seen["expected_client_id"] == 681
    assert len(calls) == 1
    assert calls[0][1]["perm_id"] == 880077


def test_unknown_recovery_rejects_ambiguous_or_conflicting_broker_identity(monkeypatch):
    journal = {
        "state": "UNKNOWN",
        "order_id": 77,
        "perm_id": None,
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
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
            "client_id": 681,
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
            "client_id": 681,
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
            "client_id": 681,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "0001.crash.01",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
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
            "client_id": 681,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "bad",
            "order_id": "77",
            "perm_id": 880077,
            "client_id": 681,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
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
            "client_id": 681,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
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
            "client_id": 681,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
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
            "client_id": 681,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
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
            "client_id": 681,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
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
            "client_id": 681,
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
        "load_send_journal",
        lambda *args, **kwargs: _bound_journal(),
    )
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "malformed",
            "order_id": "+77",
            "perm_id": 880077,
            "client_id": 681,
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
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "good",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
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



def test_postfill_proven_revalidation_rejects_wrong_sender_client_id(monkeypatch):
    journal = {
        "state": "POSTFILL_PROVEN",
        "order_id": 77,
        "perm_id": 880077,
        "sender_client_id": 681,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
    }
    payload = _postfill_payload()
    payload["executions"] = [
        {
            "exec_id": "wrong-client",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 672,
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
        lambda *args, **kwargs: pytest.fail("already-proven journal must not be rewritten"),
    )

    subject._promote_postfill_if_proven(_request())



@pytest.mark.parametrize(
    "overrides",
    [
        {"ticker": "AAPL"},
        {"side": "SELL"},
        {"quantity": 99},
        {"limit_price": 401.0},
        {"estimated_notional_jpy": 40_100.0},
        {"expected_account_fingerprint": "b" * 64},
        {"nonce": "different-nonce"},
    ],
)
def test_recovery_request_must_match_durable_consumed_authorization(
    monkeypatch, overrides
):
    monkeypatch.setattr(
        subject,
        "global_send_attempt_recorded",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        subject,
        "load_send_journal",
        lambda *args, **kwargs: _bound_journal(),
    )
    monkeypatch.setattr(
        subject,
        "audit_live_pilot_source_cutover",
        lambda **kwargs: pytest.fail(
            "source audit must be unreachable when recovery binding mismatches"
        ),
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "broker recovery must be unreachable when authorization binding mismatches"
        ),
    )
    monkeypatch.setattr(
        subject,
        "send_exactly_one_live_pilot",
        lambda *args, **kwargs: pytest.fail(
            "sender must always remain unreachable after campaign marker"
        ),
    )

    result = subject.run_live_pilot_operational_once(_request(**overrides))

    assert result.status == "BLOCKED_AUTHORIZATION_BINDING"
    assert result.recovery_only is True
    assert result.complete is False
    assert result.broker_connection_used is False
    assert result.order_transport_called is False


def test_recovery_authorization_overflowing_numbers_fail_closed():
    journal = _bound_journal(
        authorized_limit_price=10**10000,
        authorized_estimated_notional_jpy=10**10000,
    )

    assert subject._request_matches_durable_authorization(
        _request(),
        journal,
    ) is False


def test_exact_recovery_request_binding_is_accepted(monkeypatch):
    assert subject._request_matches_durable_authorization(
        _request(),
        _bound_journal(),
    ) is True



def _terminal_reports(*, executions, position):
    checked = "2026-09-21T12:39:30+00:00"
    postfill = {
        "schema_version": subject.LIVE_POSTFILL_SCHEMA_VERSION,
        "ready": True,
        "checked_at": checked,
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "executions": executions,
        "commissions": [
            {
                "exec_id": row["exec_id"],
                "commission": 10.0,
                "currency": "JPY",
            }
            for row in executions
            if row.get("order_id") == 77
        ],
        "order_sent": False,
        "live_order_sent": False,
    }
    positions = []
    if position != 0:
        positions.append(
            {
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "quantity": position,
            }
        )
    account = {
        "schema_version": subject.LIVE_ACCOUNT_SCHEMA_VERSION,
        "ready": True,
        "checked_at": checked,
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "positions": positions,
        "order_sent": False,
        "live_order_sent": False,
    }
    open_orders = {
        "schema_version": subject.LIVE_OPEN_ORDERS_SCHEMA_VERSION,
        "ready": True,
        "checked_at": checked,
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "open_order_count": 0,
        "orders": [],
        "order_sent": False,
        "cancel_sent": False,
        "live_order_sent": False,
    }
    paper = {
        "schema_version": 1,
        "status": "HEALTHY",
        "checked_at": checked,
        "accounting_safe": True,
        "risk_safe": True,
        "monitor_order_sent": False,
        "live_order_sent": False,
        "broker": {
            "account_ready": True,
            "execution_snapshot_ready": True,
            "all_open_orders_ready": True,
            "endpoint_port": 4002,
            "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
            "reconciliation_blocker_count": 0,
            "open_order_count": 0,
            "open_orders": [],
        },
    }
    return postfill, account, open_orders, paper


def _terminal_completed_report(*, orders=None):
    rows = list(orders or [])
    return {
        "schema_version": subject.LIVE_COMPLETED_ORDERS_SCHEMA_VERSION,
        "ready": True,
        "checked_at": "2026-09-21T12:39:30+00:00",
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "raw_account_id_persisted": False,
        "completed_order_count": len(rows),
        "orders": rows,
        "order_sent": False,
        "cancel_sent": False,
        "modify_sent": False,
        "live_order_sent": False,
    }


def _terminal_journal(**overrides):
    data = {
        "state": "UNKNOWN",
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "authorized_ticker": "9432.T",
        "authorized_side": "BUY",
        "authorized_quantity": 100,
        "authorized_limit_price": 400.0,
        "authorized_estimated_notional_jpy": 40_000.0,
        "authorized_account_fingerprint": FINGERPRINT,
        "authorized_endpoint_port": 4001,
        "order_id": 77,
        "perm_id": 880077,
        "sender_client_id": 681,
        "unknown_reason": "broker orderStatus callback reported non-accepted status: Inactive",
    }
    data.update(overrides)
    return data


def test_recovery_collectors_use_durable_authorized_endpoint(monkeypatch):
    journal = _terminal_journal(authorized_endpoint_port=7496)
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    seen = []

    monkeypatch.setattr(
        subject,
        "preview_ibkr_live_postfill_snapshot",
        lambda **kwargs: seen.append(("postfill", kwargs["endpoint_port"]))
        or SimpleNamespace(),
    )
    monkeypatch.setattr(subject, "persist_live_postfill_snapshot", lambda value: None)
    monkeypatch.setattr(
        subject,
        "preview_ibkr_live_readonly_account_snapshot",
        lambda **kwargs: seen.append(("account", kwargs["endpoint_port"]))
        or SimpleNamespace(),
    )
    monkeypatch.setattr(
        subject, "persist_live_readonly_account_snapshot", lambda value: None
    )
    monkeypatch.setattr(
        subject,
        "preview_ibkr_live_all_open_orders",
        lambda **kwargs: seen.append(("open_orders", kwargs["endpoint_port"]))
        or SimpleNamespace(),
    )
    monkeypatch.setattr(subject, "persist_live_all_open_orders", lambda value: None)
    monkeypatch.setattr(
        subject,
        "preview_ibkr_live_completed_orders",
        lambda **kwargs: seen.append(("completed_orders", kwargs["endpoint_port"]))
        or SimpleNamespace(),
    )
    monkeypatch.setattr(subject, "persist_live_completed_orders", lambda value: None)

    subject._collect_post_attempt_readonly_evidence(_request())

    assert seen == [
        ("postfill", 7496),
        ("account", 7496),
        ("open_orders", 7496),
        ("completed_orders", 7496),
    ]


def test_partial_fill_becomes_terminal_reconciled_without_sending_remainder(monkeypatch):
    journal = _terminal_journal()
    executions = [
        {
            "exec_id": "partial-1",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 40.0,
            "price": 402.0,
            "account_fingerprint": FINGERPRINT,
        }
    ]
    postfill, account, open_orders, paper = _terminal_reports(
        executions=executions, position=40.0
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    calls = []
    monkeypatch.setattr(
        subject,
        "mark_partial_reconciled",
        lambda *args, **kwargs: calls.append(kwargs) or {},
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail("rejected path must be unreachable"),
    )

    status = subject._promote_terminal_reconciliation_if_proven(_request())

    assert status == "PARTIAL_RECONCILED"
    assert len(calls) == 1
    assert calls[0]["exec_ids"] == ("partial-1",)
    assert calls[0]["filled_quantity"] == 40.0
    assert calls[0]["final_position_quantity"] == 40.0


def test_partial_reconciliation_decimal_overflow_fails_closed(monkeypatch):
    journal = _terminal_journal()
    executions = [
        {
            "exec_id": "overflow-1",
            "order_id": 77,
            "perm_id": 880077,
            "client_id": 681,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": "1e1000000",
            "price": 402.0,
            "account_fingerprint": FINGERPRINT,
        }
    ]
    postfill, account, open_orders, paper = _terminal_reports(
        executions=executions,
        position=0.0,
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "mark_partial_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "overflowing quantity must not be promoted"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "overflowing quantity must not enter rejection path"
        ),
    )

    assert subject._promote_terminal_reconciliation_if_proven(_request()) is None


@pytest.mark.parametrize(
    "journal_state,journal_perm_id",
    [
        ("ORDER_ACKNOWLEDGED", 880077),
        ("SEND_ATTEMPT_RECORDED", None),
    ],
)
def test_cancelled_order_is_reconciled_from_completed_history_and_binds_missing_permid(
    monkeypatch,
    journal_state,
    journal_perm_id,
):
    journal = _terminal_journal(
        state=journal_state,
        perm_id=journal_perm_id,
        unknown_reason=None,
    )
    postfill, account, open_orders, paper = _terminal_reports(
        executions=[], position=0.0
    )
    completed = {
        "schema_version": subject.LIVE_COMPLETED_ORDERS_SCHEMA_VERSION,
        "ready": True,
        "checked_at": "2026-09-21T12:39:30+00:00",
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "raw_account_id_persisted": False,
        "completed_order_count": 1,
        "orders": [
            {
                "order_id": 77,
                "perm_id": 880077,
                "client_id": 681,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "exchange": "TSEJ",
                "action": "BUY",
                "quantity": 100.0,
                "order_type": "LMT",
                "limit_price": 400.0,
                "status": "Cancelled",
                "completed_status": "Cancelled",
                "completed_time": "20260921 12:39:20 UTC",
                "order_ref": _request().intent_id,
                "account_fingerprint": FINGERPRINT,
            }
        ],
        "order_sent": False,
        "cancel_sent": False,
        "modify_sent": False,
        "live_order_sent": False,
    }
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_LIVE_COMPLETED_ORDERS_REPORT: completed,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: None,
    )

    persisted = {}

    def fake_record(*args, **kwargs):
        persisted.update(kwargs)
        return {
            "schema_version": subject.SEND_JOURNAL_SCHEMA_VERSION,
            "intent_id": _request().intent_id,
            "nonce": _request().nonce,
            "ticker": "9432.T",
            "side": "BUY",
            "quantity": 100,
            "limit_price": 400.0,
            "estimated_notional_jpy": 40_000.0,
            "account_fingerprint": FINGERPRINT,
            "endpoint_port": 4001,
            "order_id": 77,
            "perm_id": 880077,
            "sender_client_id": 681,
            "send_attempt_recorded_at": "2026-09-21T12:39:00+00:00",
            "rejection_recorded_at": "2026-09-21T12:39:30+00:00",
            "rejection_reason": (
                "broker completedOrder callback reported terminal status: Cancelled"
            ),
            "automatic_resend_allowed": False,
            "automatic_cancel_allowed": False,
            "automatic_modify_allowed": False,
            "automatic_flatten_allowed": False,
            "automatic_close_allowed": False,
            "order_sent": False,
            "live_order_sent": False,
        }

    monkeypatch.setattr(subject, "record_definitive_rejection_evidence", fake_record)
    reconciled = []
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: reconciled.append(kwargs) or {},
    )

    result = subject._promote_terminal_reconciliation_if_proven(_request())

    assert result == "REJECTED_RECONCILED"
    assert persisted["perm_id"] == 880077
    assert persisted["rejection_reason"].endswith("Cancelled")
    assert reconciled[0]["perm_id"] == 880077


def test_post_ack_completed_order_identity_mismatch_stays_unknown(monkeypatch):
    journal = _terminal_journal(
        state="ORDER_ACKNOWLEDGED",
        perm_id=880077,
        unknown_reason=None,
    )
    completed = {
        "schema_version": subject.LIVE_COMPLETED_ORDERS_SCHEMA_VERSION,
        "ready": True,
        "checked_at": "2026-09-21T12:39:30+00:00",
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "raw_account_id_persisted": False,
        "completed_order_count": 1,
        "orders": [
            {
                "order_id": 77,
                "perm_id": 880077,
                "client_id": 999,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "exchange": "TSEJ",
                "action": "BUY",
                "quantity": 100.0,
                "order_type": "LMT",
                "limit_price": 400.0,
                "status": "Cancelled",
                "completed_status": "Cancelled",
                "completed_time": "20260921 12:39:20 UTC",
                "order_ref": _request().intent_id,
                "account_fingerprint": FINGERPRINT,
            }
        ],
        "order_sent": False,
        "cancel_sent": False,
        "modify_sent": False,
        "live_order_sent": False,
    }

    assert (
        subject._completed_order_rejection_if_proven(
            _request(),
            journal,
            completed,
            endpoint_port=4001,
            order_id=77,
            sender_client_id=681,
            now=datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
        )
        is None
    )


def test_explicit_rejection_with_no_fill_becomes_terminal_reconciled(monkeypatch):
    journal = _terminal_journal(
        perm_id=None,
        unknown_reason="broker orderStatus callback reported non-accepted status: Cancelled",
    )
    postfill, account, open_orders, paper = _terminal_reports(
        executions=[], position=0.0
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_LIVE_COMPLETED_ORDERS_REPORT: _terminal_completed_report(),
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: {
            "schema_version": subject.SEND_JOURNAL_SCHEMA_VERSION,
            "intent_id": _request().intent_id,
            "nonce": _request().nonce,
            "ticker": "9432.T",
            "side": "BUY",
            "quantity": 100,
            "limit_price": 400.0,
            "estimated_notional_jpy": 40_000.0,
            "account_fingerprint": FINGERPRINT,
            "endpoint_port": 4001,
            "order_id": 77,
            "sender_client_id": 681,
            "send_attempt_recorded_at": "2026-09-21T12:39:00+00:00",
            "rejection_recorded_at": "2026-09-21T12:39:30+00:00",
            "rejection_reason": (
                "broker orderStatus callback reported non-accepted status: Cancelled"
            ),
            "automatic_resend_allowed": False,
            "automatic_cancel_allowed": False,
            "automatic_modify_allowed": False,
            "automatic_flatten_allowed": False,
            "automatic_close_allowed": False,
            "order_sent": False,
            "live_order_sent": False,
        },
    )
    calls = []
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: calls.append(kwargs) or {},
    )
    monkeypatch.setattr(
        subject,
        "mark_partial_reconciled",
        lambda *args, **kwargs: pytest.fail("partial path must be unreachable"),
    )

    status = subject._promote_terminal_reconciliation_if_proven(_request())

    assert status == "REJECTED_RECONCILED"
    assert len(calls) == 1
    assert calls[0]["order_id"] == 77
    assert calls[0]["final_position_quantity"] == 0.0


def test_callback_rejection_without_permid_accepts_exact_completed_cancelled_history(
    monkeypatch,
):
    journal = _terminal_journal(
        perm_id=None,
        unknown_reason=(
            "broker orderStatus callback reported non-accepted status: Cancelled"
        ),
    )
    postfill, account, open_orders, paper = _terminal_reports(
        executions=[
            {
                "exec_id": "unrelated-cross-client",
                "order_id": 77,
                "perm_id": 990088,
                "client_id": 999,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "side": "BUY",
                "quantity": 1.0,
                "price": 402.0,
                "time": "2026-09-21T12:39:19+00:00",
                "account_fingerprint": FINGERPRINT,
            }
        ],
        position=0.0,
    )
    completed = _terminal_completed_report(
        orders=[
            {
                "order_id": 77,
                "perm_id": 880077,
                "client_id": 681,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "exchange": "TSEJ",
                "action": "BUY",
                "quantity": 100.0,
                "order_type": "LMT",
                "limit_price": 400.0,
                "status": "Cancelled",
                "completed_status": "Cancelled",
                "completed_time": "20260921 12:39:20 UTC",
                "order_ref": _request().intent_id,
                "account_fingerprint": FINGERPRINT,
            }
        ]
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_LIVE_COMPLETED_ORDERS_REPORT: completed,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    rejection = _persisted_rejection_evidence()

    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: rejection,
    )
    calls = []
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: calls.append(kwargs) or {},
    )

    result = subject._promote_terminal_reconciliation_if_proven(_request())

    assert result == "REJECTED_RECONCILED"
    assert len(calls) == 1
    assert calls[0]["order_id"] == 77
    assert calls[0]["perm_id"] is None


def test_missing_rejection_permid_blocks_cross_client_execution_using_derived_permid(
    monkeypatch,
):
    journal = _terminal_journal(
        perm_id=None,
        unknown_reason=(
            "broker orderStatus callback reported non-accepted status: Cancelled"
        ),
    )
    executions = [
        {
            "exec_id": "conflicting-exec",
            "order_id": 78,
            "perm_id": 880077,
            "client_id": 999,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 402.0,
            "time": "2026-09-21T12:39:20+00:00",
            "account_fingerprint": FINGERPRINT,
        }
    ]
    postfill, account, open_orders, paper = _terminal_reports(
        executions=executions,
        position=0.0,
    )
    completed = _terminal_completed_report(
        orders=[
            {
                "order_id": 77,
                "perm_id": 880077,
                "client_id": 681,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "exchange": "TSEJ",
                "action": "BUY",
                "quantity": 100.0,
                "order_type": "LMT",
                "limit_price": 400.0,
                "status": "Cancelled",
                "completed_status": "Cancelled",
                "completed_time": "20260921 12:39:20 UTC",
                "order_ref": _request().intent_id,
                "account_fingerprint": FINGERPRINT,
            }
        ]
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_LIVE_COMPLETED_ORDERS_REPORT: completed,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    rejection = _persisted_rejection_evidence()

    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: rejection,
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "derived completed permId must block the conflicting execution"
        ),
    )

    assert subject._promote_terminal_reconciliation_if_proven(_request()) is None


def test_missing_rejection_permid_still_rejects_completed_permid_conflict(
    monkeypatch,
):
    journal = _terminal_journal(
        perm_id=None,
        unknown_reason=(
            "broker orderStatus callback reported non-accepted status: Cancelled"
        ),
    )
    postfill, account, open_orders, paper = _terminal_reports(
        executions=[],
        position=0.0,
    )
    completed = _terminal_completed_report(
        orders=[
            {
                "order_id": 77,
                "perm_id": 880077,
                "client_id": 681,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "exchange": "TSEJ",
                "action": "BUY",
                "quantity": 100.0,
                "order_type": "LMT",
                "limit_price": 400.0,
                "status": "Cancelled",
                "completed_status": "Cancelled",
                "completed_time": "20260921 12:39:20 UTC",
                "order_ref": _request().intent_id,
                "account_fingerprint": FINGERPRINT,
            },
            {
                "order_id": 78,
                "perm_id": 880077,
                "client_id": 999,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "exchange": "TSEJ",
                "action": "BUY",
                "quantity": 100.0,
                "order_type": "LMT",
                "limit_price": 400.0,
                "status": "Filled",
                "completed_status": "Filled",
                "completed_time": "20260921 12:39:21 UTC",
                "order_ref": "other-intent",
                "account_fingerprint": FINGERPRINT,
            },
        ]
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_LIVE_COMPLETED_ORDERS_REPORT: completed,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    rejection = _persisted_rejection_evidence()

    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: rejection,
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "derived permId conflict must block rejection promotion"
        ),
    )

    assert subject._promote_terminal_reconciliation_if_proven(_request()) is None


def test_rejection_recovery_rejects_reverse_permid_collision(monkeypatch):
    journal = _terminal_journal(
        perm_id=880077,
        unknown_reason=(
            "broker orderStatus callback reported non-accepted status: Cancelled"
        ),
    )
    executions = [
        {
            "exec_id": "conflicting-exec",
            "order_id": 78,
            "perm_id": 880077,
            "client_id": 681,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 402.0,
            "account_fingerprint": FINGERPRINT,
        }
    ]
    postfill, account, open_orders, paper = _terminal_reports(
        executions=executions,
        position=0.0,
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    rejection = _persisted_rejection_evidence()
    rejection["perm_id"] = 880077

    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: rejection,
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "reverse permId collision must block rejection promotion"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_partial_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "different order_id must not enter partial reconciliation"
        ),
    )

    assert subject._promote_terminal_reconciliation_if_proven(_request()) is None


def test_existing_rejection_proof_revalidates_fresh_completed_conflicts(
    monkeypatch,
):
    journal = _terminal_journal(
        perm_id=880077,
        unknown_reason=(
            "broker orderStatus callback reported non-accepted status: Cancelled"
        ),
    )
    postfill, account, open_orders, paper = _terminal_reports(
        executions=[],
        position=0.0,
    )
    conflicting_completed = _terminal_completed_report(
        orders=[
            {
                "order_id": 77,
                "perm_id": 880077,
                "client_id": 999,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "exchange": "TSEJ",
                "action": "BUY",
                "quantity": 100.0,
                "order_type": "LMT",
                "limit_price": 400.0,
                "status": "Filled",
                "completed_status": "Filled",
                "completed_time": "20260921 12:39:20 UTC",
                "order_ref": _request().intent_id,
                "account_fingerprint": FINGERPRINT,
            }
        ]
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_LIVE_COMPLETED_ORDERS_REPORT: conflicting_completed,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    rejection = _persisted_rejection_evidence()
    rejection["perm_id"] = 880077

    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: rejection,
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "fresh completed-order contradiction must block rejection promotion"
        ),
    )

    assert subject._promote_terminal_reconciliation_if_proven(_request()) is None


def test_execution_conflict_blocks_before_completed_rejection_proof_is_frozen(
    monkeypatch,
):
    journal = _terminal_journal(
        state="ORDER_ACKNOWLEDGED",
        perm_id=880077,
        unknown_reason=None,
    )
    executions = [
        {
            "exec_id": "reverse-collision",
            "order_id": 78,
            "perm_id": 880077,
            "client_id": 681,
            "symbol": "9432",
            "sec_type": "STK",
            "currency": "JPY",
            "side": "BUY",
            "quantity": 1.0,
            "price": 402.0,
            "account_fingerprint": FINGERPRINT,
        }
    ]
    postfill, account, open_orders, paper = _terminal_reports(
        executions=executions,
        position=0.0,
    )
    completed = _terminal_completed_report(
        orders=[
            {
                "order_id": 77,
                "perm_id": 880077,
                "client_id": 681,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "exchange": "TSEJ",
                "action": "BUY",
                "quantity": 100.0,
                "order_type": "LMT",
                "limit_price": 400.0,
                "status": "Cancelled",
                "completed_status": "Cancelled",
                "completed_time": "20260921 12:39:20 UTC",
                "order_ref": _request().intent_id,
                "account_fingerprint": FINGERPRINT,
            }
        ]
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_LIVE_COMPLETED_ORDERS_REPORT: completed,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }

    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        subject,
        "record_definitive_rejection_evidence",
        lambda *args, **kwargs: pytest.fail(
            "execution conflict must block before immutable rejection proof"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "execution conflict must block rejection promotion"
        ),
    )

    assert subject._promote_terminal_reconciliation_if_proven(_request()) is None


def test_malformed_nonnull_perm_id_blocks_rejection_promotion(monkeypatch):
    journal = _terminal_journal(
        perm_id="880077",
        unknown_reason=(
            "broker orderStatus callback reported non-accepted status: Cancelled"
        ),
    )
    postfill, account, open_orders, paper = _terminal_reports(
        executions=[],
        position=0.0,
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports[path])
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: _persisted_rejection_evidence(),
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "malformed non-null perm_id must block rejection promotion"
        ),
    )
    monkeypatch.setattr(
        subject,
        "mark_partial_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "no executions means partial path must be unreachable"
        ),
    )

    assert subject._promote_terminal_reconciliation_if_proven(_request()) is None


def test_timeout_without_definitive_rejection_remains_unknown(monkeypatch):
    journal = _terminal_journal(
        perm_id=None, unknown_reason="broker acknowledgement timed out"
    )
    postfill, account, open_orders, paper = _terminal_reports(
        executions=[], position=0.0
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports.get(path))
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {
            "recorded_at": "2026-09-21T12:39:00+00:00"
        },
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail("timeout must remain UNKNOWN"),
    )
    monkeypatch.setattr(
        subject,
        "mark_partial_reconciled",
        lambda *args, **kwargs: pytest.fail("no fill means no partial state"),
    )

    assert subject._promote_terminal_reconciliation_if_proven(_request()) is None


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            "broker orderStatus callback reported non-accepted status: Inactive",
            False,
        ),
        (
            "broker openOrder callback reported non-accepted status: Cancelled",
            True,
        ),
        ("77:201:Order rejected - Reason: test", True),
        ("77:202:Order cancelled - Reason: test", True),
        ("77:399:Order message error", False),
        ("77:2104:Market data farm connection is OK", False),
        (
            "broker orderStatus callback reported non-accepted status: PendingSubmit",
            False,
        ),
        (
            "broker openOrder callback reported non-accepted status: PendingCancel",
            False,
        ),
    ],
)
def test_definitive_rejection_classifier_is_fail_closed(reason, expected):
    observed = subject._definitive_rejection_reason(reason)
    assert (observed is not None) is expected


def _persisted_terminal_journal(terminal_state: str) -> dict:
    data = _bound_journal(
        schema_version=subject.SEND_JOURNAL_SCHEMA_VERSION,
        state=terminal_state,
        send_attempt_count=1,
        recovery_required=False,
        order_sent=False,
        live_order_sent=False,
        automatic_resend_allowed=False,
        automatic_cancel_allowed=False,
        automatic_modify_allowed=False,
        automatic_flatten_allowed=False,
        automatic_close_allowed=False,
        sender_client_id=681,
        order_id=77,
        send_attempt_recorded_at="2026-09-21T12:39:00+00:00",
        reconciled_at="2026-09-21T12:40:00+00:00",
    )
    if terminal_state == "PARTIAL_RECONCILED":
        data.update(
            perm_id=880077,
            exec_ids=["partial-1"],
            filled_quantity=40.0,
            commission_total=10.0,
            commission_currency="JPY",
            final_position_quantity=40.0,
        )
    else:
        data.update(
            perm_id=None,
            rejection_reason=(
                "broker orderStatus callback reported non-accepted status: Cancelled"
            ),
            final_position_quantity=0.0,
        )
    return data


def _persisted_terminal_marker(terminal_state: str) -> dict:
    journal = _persisted_terminal_journal(terminal_state)
    marker = {
        key: journal[key]
        for key in (
            "intent_id",
            "nonce",
            "authorized_ticker",
            "authorized_side",
            "authorized_quantity",
            "authorized_limit_price",
            "authorized_estimated_notional_jpy",
            "authorized_account_fingerprint",
            "authorized_endpoint_port",
            "send_attempt_count",
            "order_id",
            "sender_client_id",
            "recovery_required",
            "automatic_resend_allowed",
            "automatic_cancel_allowed",
            "automatic_modify_allowed",
            "automatic_flatten_allowed",
            "automatic_close_allowed",
            "order_sent",
            "live_order_sent",
        )
    }
    marker.update(
        schema_version=subject.SEND_JOURNAL_SCHEMA_VERSION,
        state=terminal_state,
        send_attempt_recorded_at="2026-09-21T12:39:00+00:00",
        terminal_recorded_at="2026-09-21T12:40:00+00:00",
    )
    if terminal_state == "PARTIAL_RECONCILED":
        marker.update(
            perm_id=880077,
            exec_ids=["partial-1"],
            filled_quantity=40.0,
            commission_total=10.0,
            commission_currency="JPY",
            final_position_quantity=40.0,
        )
    else:
        marker.update(
            perm_id=None,
            rejection_reason=(
                "broker orderStatus callback reported non-accepted status: Cancelled"
            ),
            final_position_quantity=0.0,
        )
    return marker


def _persisted_rejection_evidence() -> dict:
    return {
        "schema_version": subject.SEND_JOURNAL_SCHEMA_VERSION,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "ticker": "9432.T",
        "side": "BUY",
        "quantity": 100,
        "limit_price": 400.0,
        "estimated_notional_jpy": 40_000.0,
        "account_fingerprint": FINGERPRINT,
        "endpoint_port": 4001,
        "order_id": 77,
        "sender_client_id": 681,
        "send_attempt_recorded_at": "2026-09-21T12:39:00+00:00",
        "rejection_recorded_at": "2026-09-21T12:39:30+00:00",
        "rejection_reason": (
            "broker orderStatus callback reported non-accepted status: Cancelled"
        ),
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
        "order_sent": False,
        "live_order_sent": False,
    }


def _terminal_attempt_marker() -> dict:
    return {
        "schema_version": subject.SEND_JOURNAL_SCHEMA_VERSION,
        "intent_id": _request().intent_id,
        "nonce": _request().nonce,
        "state": "SEND_ATTEMPT_RECORDED",
        "recorded_at": "2026-09-21T12:39:00+00:00",
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
    }


def _terminal_global_marker() -> dict:
    return {
        "schema_version": subject.SEND_JOURNAL_SCHEMA_VERSION,
        "intent_id": _request().intent_id,
        "recorded_at": "2026-09-21T12:39:00+00:00",
        "automatic_resend_allowed": False,
    }


@pytest.mark.parametrize("terminal_state", ["PARTIAL_RECONCILED", "REJECTED_RECONCILED"])
def test_persisted_terminal_reconciliation_surfaces_without_new_broker_io(
    monkeypatch, terminal_state
):
    journal = _persisted_terminal_journal(terminal_state)
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: _persisted_terminal_marker(terminal_state),
    )
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: _terminal_attempt_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_global_send_attempt_marker",
        lambda *args, **kwargs: _terminal_global_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: _persisted_rejection_evidence(),
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "already terminal recovery must not reconnect to the broker"
        ),
    )
    monkeypatch.setattr(
        subject,
        "audit_live_pilot_completion",
        lambda *args, **kwargs: pytest.fail(
            "already terminal recovery must not fall through to full-fill judge"
        ),
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == terminal_state
    assert result.completion_status == terminal_state
    assert result.complete is True
    assert result.recovery_only is True
    assert result.broker_connection_used is False
    assert result.order_transport_called is False


@pytest.mark.parametrize(
    ("terminal_state", "missing_key"),
    [
        ("PARTIAL_RECONCILED", "exec_ids"),
        ("PARTIAL_RECONCILED", "commission_currency"),
        ("REJECTED_RECONCILED", "rejection_reason"),
        ("REJECTED_RECONCILED", "final_position_quantity"),
    ],
)
def test_malformed_persisted_terminal_evidence_blocks_without_broker_io(
    monkeypatch, terminal_state, missing_key
):
    journal = _persisted_terminal_journal(terminal_state)
    terminal = _persisted_terminal_marker(terminal_state)
    terminal.pop(missing_key)
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: terminal,
    )
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: _terminal_attempt_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_global_send_attempt_marker",
        lambda *args, **kwargs: _terminal_global_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: _persisted_rejection_evidence(),
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "invalid terminal evidence must fail before broker recovery"
        ),
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "BLOCKED_TERMINAL_EVIDENCE"
    assert result.complete is False
    assert result.broker_connection_used is False
    assert result.order_transport_called is False

def test_terminal_reconciliation_requires_both_irreversible_markers(monkeypatch):
    journal = _persisted_terminal_journal("REJECTED_RECONCILED")
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: _persisted_terminal_marker("REJECTED_RECONCILED"),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: _persisted_rejection_evidence(),
    )
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: _terminal_attempt_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_global_send_attempt_marker",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "missing campaign marker must fail before broker recovery"
        ),
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "BLOCKED_TERMINAL_EVIDENCE"
    assert result.complete is False
    assert result.broker_connection_used is False


def test_terminal_marker_is_authoritative_over_edited_summary_payload(monkeypatch):
    journal = _persisted_terminal_journal("PARTIAL_RECONCILED")
    journal["exec_ids"] = ["fabricated-summary"]
    journal["filled_quantity"] = 99.0
    journal["commission_total"] = 9999.0
    journal["final_position_quantity"] = 99.0
    terminal = _persisted_terminal_marker("PARTIAL_RECONCILED")

    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: terminal,
    )
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: _terminal_attempt_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_global_send_attempt_marker",
        lambda *args, **kwargs: _terminal_global_marker(),
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "valid immutable terminal proof must not reconnect"
        ),
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "PARTIAL_RECONCILED"
    assert result.complete is True
    assert result.broker_connection_used is False


def test_terminal_marker_surfaces_after_crash_before_summary_transition(monkeypatch):
    journal = _persisted_terminal_journal("PARTIAL_RECONCILED")
    journal["state"] = "UNKNOWN"
    journal["recovery_required"] = True
    journal.pop("reconciled_at", None)
    terminal = _persisted_terminal_marker("PARTIAL_RECONCILED")

    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: terminal,
    )
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: _terminal_attempt_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_global_send_attempt_marker",
        lambda *args, **kwargs: _terminal_global_marker(),
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "exclusive terminal marker must survive summary-write crash"
        ),
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "PARTIAL_RECONCILED"
    assert result.complete is True
    assert result.broker_connection_used is False


def test_new_terminal_transition_is_revalidated_before_complete(monkeypatch):
    journal = _terminal_journal()
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(subject, "_promote_postfill_if_proven", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        subject,
        "_promote_terminal_reconciliation_if_proven",
        lambda *args, **kwargs: "PARTIAL_RECONCILED",
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "BLOCKED_TERMINAL_EVIDENCE"
    assert result.complete is False
    assert result.broker_connection_used is True


def test_terminal_transition_marker_failure_returns_blocked_result(monkeypatch):
    journal = _terminal_journal()
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(subject, "_promote_postfill_if_proven", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        subject,
        "_promote_terminal_reconciliation_if_proven",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PermissionError("irreversible attempt marker binding is invalid")
        ),
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "BLOCKED_TERMINAL_EVIDENCE"
    assert result.complete is False
    assert result.broker_connection_used is True
    assert result.order_transport_called is False


def test_mutable_unknown_reason_cannot_manufacture_rejection_without_immutable_proof(
    monkeypatch,
):
    journal = _terminal_journal(
        perm_id=None,
        unknown_reason="77:201:fabricated mutable rejection",
    )
    postfill, account, open_orders, paper = _terminal_reports(
        executions=[], position=0.0
    )
    reports = {
        subject.DEFAULT_POSTFILL_REPORT: postfill,
        subject.DEFAULT_LIVE_ACCOUNT_REPORT: account,
        subject.DEFAULT_LIVE_OPEN_ORDERS_REPORT: open_orders,
        subject.DEFAULT_PAPER_MONITOR_REPORT: paper,
    }
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(subject, "_load_json", lambda path: reports.get(path))
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: {"recorded_at": "2026-09-21T12:39:00+00:00"},
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        subject,
        "_utc_now",
        lambda: datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        subject,
        "mark_rejected_reconciled",
        lambda *args, **kwargs: pytest.fail(
            "mutable unknown_reason must never create terminal rejection"
        ),
    )

    assert subject._promote_terminal_reconciliation_if_proven(_request()) is None


@pytest.mark.parametrize("field", ["order_id", "sender_client_id"])
def test_unhashable_terminal_broker_identity_blocks_instead_of_raising(
    monkeypatch, field
):
    journal = _persisted_terminal_journal("PARTIAL_RECONCILED")
    terminal = _persisted_terminal_marker("PARTIAL_RECONCILED")
    terminal[field] = []

    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: terminal,
    )
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: _terminal_attempt_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_global_send_attempt_marker",
        lambda *args, **kwargs: _terminal_global_marker(),
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "malformed terminal identity must block before broker recovery"
        ),
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "BLOCKED_TERMINAL_EVIDENCE"
    assert result.complete is False
    assert result.broker_connection_used is False


def test_persisted_rejected_terminal_requires_immutable_callback_evidence(monkeypatch):
    journal = _persisted_terminal_journal("REJECTED_RECONCILED")
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: _persisted_terminal_marker("REJECTED_RECONCILED"),
    )
    monkeypatch.setattr(
        subject,
        "load_send_attempt_marker",
        lambda *args, **kwargs: _terminal_attempt_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_global_send_attempt_marker",
        lambda *args, **kwargs: _terminal_global_marker(),
    )
    monkeypatch.setattr(
        subject,
        "load_definitive_rejection_evidence",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "missing immutable rejection proof must block before broker recovery"
        ),
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "BLOCKED_TERMINAL_EVIDENCE"
    assert result.complete is False
    assert result.broker_connection_used is False


def test_unreadable_journal_inside_reconcile_returns_blocked_without_broker_io(
    monkeypatch,
):
    monkeypatch.setattr(
        subject,
        "load_send_journal",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            UnicodeError("journal bytes are unreadable")
        ),
    )
    monkeypatch.setattr(
        subject,
        "_collect_post_attempt_readonly_evidence",
        lambda *args, **kwargs: pytest.fail(
            "broker recovery must be unreachable when journal cannot be read"
        ),
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "BLOCKED_TERMINAL_EVIDENCE"
    assert result.recovery_only is True
    assert result.complete is False
    assert result.broker_connection_used is False
    assert result.order_transport_called is False
    assert any("journal is unreadable" in item for item in result.blockers)


def test_malformed_nonterminal_recovery_binding_returns_blocked_without_broker_io(
    monkeypatch,
):
    journal = _terminal_journal()
    journal["sender_client_id"] = []
    monkeypatch.setattr(subject, "load_send_journal", lambda *args, **kwargs: journal)
    monkeypatch.setattr(
        subject,
        "load_terminal_reconciliation_marker",
        lambda *args, **kwargs: None,
    )

    result = subject._reconcile_once(
        _request(),
        send_status=None,
        order_transport_called=False,
    )

    assert result.status == "BLOCKED_TERMINAL_EVIDENCE"
    assert result.complete is False
    assert result.broker_connection_used is False
    assert result.order_transport_called is False
    assert any("recovery broker identity is invalid" in item for item in result.blockers)


def test_completed_order_recovery_matches_order_id_with_sender_client():
    journal = _terminal_journal(
        state="ORDER_ACKNOWLEDGED",
        perm_id=880077,
        unknown_reason=None,
    )
    request = _request()
    base_row = {
        "order_id": 77,
        "perm_id": 880077,
        "client_id": 681,
        "symbol": "9432",
        "sec_type": "STK",
        "currency": "JPY",
        "exchange": "TSEJ",
        "action": "BUY",
        "quantity": 100.0,
        "order_type": "LMT",
        "limit_price": 400.0,
        "status": "Cancelled",
        "completed_status": "Cancelled",
        "completed_time": "20260921 12:39:20 UTC",
        "order_ref": request.intent_id,
        "account_fingerprint": FINGERPRINT,
    }
    other_client_row = {
        **base_row,
        "perm_id": 990077,
        "client_id": 999,
        "completed_time": "20260921 12:39:19 UTC",
    }
    completed = {
        "schema_version": subject.LIVE_COMPLETED_ORDERS_SCHEMA_VERSION,
        "ready": True,
        "checked_at": "2026-09-21T12:39:30+00:00",
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "raw_account_id_persisted": False,
        "completed_order_count": 2,
        "orders": [other_client_row, base_row],
        "order_sent": False,
        "cancel_sent": False,
        "modify_sent": False,
        "live_order_sent": False,
    }

    observed = subject._completed_order_rejection_if_proven(
        request,
        journal,
        completed,
        endpoint_port=4001,
        order_id=77,
        sender_client_id=681,
        now=datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
    )

    assert observed is not None
    reason, perm_id = observed
    assert reason.endswith("Cancelled")
    assert perm_id == 880077


def test_completed_order_recovery_rejects_cross_client_selected_permid_conflict():
    journal = _terminal_journal(
        state="ORDER_ACKNOWLEDGED",
        perm_id=880077,
        unknown_reason=None,
    )
    request = _request()
    sender_row = {
        "order_id": 77,
        "perm_id": 880077,
        "client_id": 681,
        "symbol": "9432",
        "sec_type": "STK",
        "currency": "JPY",
        "exchange": "TSEJ",
        "action": "BUY",
        "quantity": 100.0,
        "order_type": "LMT",
        "limit_price": 400.0,
        "status": "Cancelled",
        "completed_status": "Cancelled",
        "completed_time": "20260921 12:39:20 UTC",
        "order_ref": request.intent_id,
        "account_fingerprint": FINGERPRINT,
    }
    conflicting_other_client = {
        **sender_row,
        "client_id": 999,
        "status": "Filled",
        "completed_status": "Filled",
        "completed_time": "20260921 12:39:21 UTC",
    }
    completed = {
        "schema_version": subject.LIVE_COMPLETED_ORDERS_SCHEMA_VERSION,
        "ready": True,
        "checked_at": "2026-09-21T12:39:30+00:00",
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "raw_account_id_persisted": False,
        "completed_order_count": 2,
        "orders": [sender_row, conflicting_other_client],
        "order_sent": False,
        "cancel_sent": False,
        "modify_sent": False,
        "live_order_sent": False,
    }

    assert (
        subject._completed_order_rejection_if_proven(
            request,
            journal,
            completed,
            endpoint_port=4001,
            order_id=77,
            sender_client_id=681,
            now=datetime(2026, 9, 21, 12, 40, tzinfo=timezone.utc),
        )
        is None
    )
