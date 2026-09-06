from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest

from ai_asset_platform.execution.live_pilot_source_cutover import (
    AUDITED_PATHS,
    audit_live_pilot_source_cutover,
    source_cutover_record,
)


NOW = datetime(2026, 9, 6, 8, 0, 0, tzinfo=timezone.utc)
SHA = "a" * 40


class FakeRunner:
    def __init__(self, *, actual_sha: str = SHA, status: str = "", fail: bool = False):
        self.actual_sha = actual_sha
        self.status = status
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        if self.fail:
            raise subprocess.CalledProcessError(1, command)
        if command[1:3] == ["rev-parse", "HEAD"]:
            stdout = self.actual_sha + "\n"
        elif command[1:3] == ["status", "--porcelain=v1"]:
            stdout = self.status
        else:
            raise AssertionError(f"unexpected git command: {command}")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def test_exact_approved_commit_and_clean_audited_paths_are_ready(tmp_path: Path):
    runner = FakeRunner()
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is True
    assert result.status == "READY_FOR_PINNED_RUNTIME"
    assert result.exact_commit_match is True
    assert result.audited_paths_clean is True
    assert result.order_sent is False
    assert result.live_order_sent is False
    status_call = runner.calls[1]
    for path in AUDITED_PATHS:
        assert path in status_call


def test_wrong_commit_sha_fails_closed(tmp_path: Path):
    runner = FakeRunner(actual_sha="b" * 40)
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.exact_commit_match is False


def test_tracked_edit_in_audited_source_fails_closed(tmp_path: Path):
    runner = FakeRunner(status=" M src/ai_asset_platform/core/settings.py\n")
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.audited_paths_clean is False
    assert result.dirty_entries == (" M src/ai_asset_platform/core/settings.py",)


def test_git_audit_failure_fails_closed(tmp_path: Path):
    runner = FakeRunner(fail=True)
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.actual_commit_sha is None
    assert result.dirty_entries == ("GIT_AUDIT_FAILED",)


def test_invalid_expected_sha_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="40-character"):
        audit_live_pilot_source_cutover(
            expected_commit_sha="main",
            repository_root=tmp_path,
            now=NOW,
            runner=FakeRunner(),
        )


def test_result_files_are_not_part_of_source_cleanliness_pathspec(tmp_path: Path):
    runner = FakeRunner()
    audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )
    status_call = runner.calls[1]
    assert "results" not in status_call


def test_record_does_not_claim_order_permission(tmp_path: Path):
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=FakeRunner(),
    )
    record = source_cutover_record(result)

    assert record["order_sent"] is False
    assert record["live_order_sent"] is False
    assert "does not authorize" in record["interpretation"]


def test_module_contains_no_broker_order_transport():
    source = Path(
        "src/ai_asset_platform/execution/live_pilot_source_cutover.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "reqOpenOrders(",
        "reqAllOpenOrders(",
        "reqExecutions(",
        "enable_live_trading = True",
        "whatIf=True",
    )
    for token in forbidden:
        assert token not in source
