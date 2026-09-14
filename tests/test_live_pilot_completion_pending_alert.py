from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

import ai_asset_platform.execution.live_pilot_completion as subject


def _result(*, complete: bool) -> subject.LivePilotCompletion:
    return subject.LivePilotCompletion(
        status="COMPLETE" if complete else "BLOCKED",
        checked_at="2026-09-09T04:00:00+00:00",
        blockers=() if complete else ("simulated blocker",),
        intent_id="live-pilot:test",
        ticker="AAPL",
        side="BUY",
        quantity=1,
        account_fingerprint="a" * 64,
        order_id=1,
        perm_id=2,
        exec_id="exec-1",
        execution_price=100.0,
        commission=1.0,
        commission_currency="USD",
        final_position_quantity=1.0 if complete else None,
        final_open_order_count=0 if complete else None,
        endpoint_port=4001 if complete else None,
        evidence_fresh=complete,
        paper_monitor_safe=complete,
        complete=complete,
    )


def test_complete_report_failure_leaves_pending_critical_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "completion.json"
    alert = tmp_path / "alert.json"
    original_write = subject._durable_write_json

    def failing_write(path: Path, payload: dict) -> None:
        if path == report:
            raise OSError("simulated report persistence failure")
        original_write(path, payload)

    monkeypatch.setattr(subject, "_durable_write_json", failing_write)

    with pytest.raises(OSError, match="simulated report persistence failure"):
        subject.persist_live_pilot_completion(
            _result(complete=True), report_path=report, alert_path=alert
        )

    alert_payload = json.loads(alert.read_text(encoding="utf-8"))
    assert not report.exists()
    assert alert_payload["status"] == "PENDING_REPORT_PERSISTENCE"
    assert alert_payload["status"] != "COMPLETE"
    assert alert_payload["severity"] == "CRITICAL"
    assert "PENDING REPORT PERSISTENCE" in alert_payload["message"]


def test_success_publishes_complete_only_after_report_persists(tmp_path: Path) -> None:
    report = tmp_path / "completion.json"
    alert = tmp_path / "alert.json"

    subject.persist_live_pilot_completion(
        _result(complete=True), report_path=report, alert_path=alert
    )

    report_payload = json.loads(report.read_text(encoding="utf-8"))
    alert_payload = json.loads(alert.read_text(encoding="utf-8"))
    assert report_payload["status"] == "COMPLETE"
    assert report_payload["complete"] is True
    assert alert_payload["status"] == "COMPLETE"
    assert alert_payload["severity"] == "SUCCESS"


def test_blocked_result_remains_non_complete(tmp_path: Path) -> None:
    report = tmp_path / "completion.json"
    alert = tmp_path / "alert.json"

    subject.persist_live_pilot_completion(
        _result(complete=False), report_path=report, alert_path=alert
    )

    alert_payload = json.loads(alert.read_text(encoding="utf-8"))
    assert alert_payload["status"] == "BLOCKED"
    assert alert_payload["severity"] == "CRITICAL"
    assert "DO NOT RETRY AUTOMATICALLY" in alert_payload["message"]

def test_overlapping_publications_leave_a_consistent_report_and_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "completion.json"
    alert = tmp_path / "alert.json"
    complete_report_written = threading.Event()
    release_complete = threading.Event()
    blocked_entered_publication = threading.Event()
    original_write = subject._durable_write_json

    def interleaving_write(path: Path, payload: dict) -> None:
        original_write(path, payload)
        if path == report and payload.get("status") == "COMPLETE":
            complete_report_written.set()
            assert release_complete.wait(timeout=5)
        if path == alert and payload.get("status") == "BLOCKED":
            blocked_entered_publication.set()

    monkeypatch.setattr(subject, "_durable_write_json", interleaving_write)

    complete_thread = threading.Thread(
        target=subject.persist_live_pilot_completion,
        args=(_result(complete=True),),
        kwargs={"report_path": report, "alert_path": alert},
    )
    blocked_thread = threading.Thread(
        target=subject.persist_live_pilot_completion,
        args=(_result(complete=False),),
        kwargs={"report_path": report, "alert_path": alert},
    )
    complete_thread.start()
    assert complete_report_written.wait(timeout=5)
    blocked_thread.start()

    assert not blocked_entered_publication.wait(timeout=0.2)
    release_complete.set()
    complete_thread.join(timeout=5)
    blocked_thread.join(timeout=5)
    assert not complete_thread.is_alive()
    assert not blocked_thread.is_alive()

    report_payload = json.loads(report.read_text(encoding="utf-8"))
    alert_payload = json.loads(alert.read_text(encoding="utf-8"))
    assert blocked_entered_publication.is_set()
    assert report_payload["status"] == "BLOCKED"
    assert report_payload["complete"] is False
    assert alert_payload["status"] == "BLOCKED"
    assert alert_payload["severity"] == "CRITICAL"
