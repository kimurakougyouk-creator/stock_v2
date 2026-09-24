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
    def __init__(
        self,
        *,
        actual_sha: str = SHA,
        status: str = "",
        ignored: str = "",
        index_flags: str = "",
        fail: bool = False,
    ):
        self.actual_sha = actual_sha
        self.status = status
        self.ignored = ignored
        self.index_flags = index_flags
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        if self.fail:
            raise subprocess.CalledProcessError(1, command)
        args = list(command[1:])
        while len(args) >= 2 and args[0] == "-c":
            args = args[2:]
        if args[:2] == ["rev-parse", "HEAD"]:
            stdout = self.actual_sha + "\n"
        elif args[:2] == ["status", "--porcelain=v1"]:
            stdout = self.status
        elif args[:2] == ["ls-files", "-v"]:
            stdout = self.index_flags
        elif args[:2] == ["ls-files", "--others"]:
            stdout = self.ignored
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
    index_call = runner.calls[2]
    ignored_call = runner.calls[3]
    for call in runner.calls:
        assert call[:5] == [
            "/usr/bin/git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
        ]
    assert "--untracked-files=all" in status_call
    def git_args(call):
        args = list(call[1:])
        while len(args) >= 2 and args[0] == "-c":
            args = args[2:]
        return args

    assert git_args(index_call)[:2] == ["ls-files", "-v"]
    assert git_args(ignored_call)[:4] == [
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
    ]
    for path in AUDITED_PATHS:
        assert path in status_call
        assert path in index_call
        assert path in ignored_call


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


def test_untracked_file_in_audited_source_fails_closed(tmp_path: Path):
    runner = FakeRunner(status="?? src/sitecustomize.py\n")
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.audited_paths_clean is False
    assert result.dirty_entries == ("?? src/sitecustomize.py",)


def test_assume_unchanged_audited_entry_fails_closed(tmp_path: Path):
    runner = FakeRunner(index_flags="h src/ai_asset_platform/execution/live_pilot_operational_entrypoint.py\n")
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.dirty_entries == (
        "INDEX_HIDDEN h src/ai_asset_platform/execution/live_pilot_operational_entrypoint.py",
    )


def test_skip_worktree_audited_entry_fails_closed(tmp_path: Path):
    runner = FakeRunner(index_flags="S src/ai_asset_platform/execution/live_pilot_operational_entrypoint.py\n")
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.dirty_entries == (
        "INDEX_HIDDEN S src/ai_asset_platform/execution/live_pilot_operational_entrypoint.py",
    )


def test_ignored_importable_artifact_in_audited_source_fails_closed(tmp_path: Path):
    runner = FakeRunner(ignored="src/sitecustomize.pyc\n")
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.audited_paths_clean is False
    assert result.dirty_entries == ("IGNORED_IMPORTABLE src/sitecustomize.pyc",)


def test_ignored_native_extension_in_audited_source_fails_closed(tmp_path: Path):
    runner = FakeRunner(ignored="src/ai_asset_platform/unsafe_shadow.so\n")
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.dirty_entries == (
        "IGNORED_IMPORTABLE src/ai_asset_platform/unsafe_shadow.so",
    )


def test_ignored_extensionless_package_symlink_fails_closed(tmp_path: Path):
    link = tmp_path / "src" / "ai_asset_platform" / "execution" / "live_pilot_operational_entrypoint"
    link.parent.mkdir(parents=True)
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "__init__.py").write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    link.symlink_to(payload, target_is_directory=True)

    runner = FakeRunner(
        ignored="src/ai_asset_platform/execution/live_pilot_operational_entrypoint\n"
    )
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.dirty_entries == (
        "IGNORED_SYMLINK src/ai_asset_platform/execution/live_pilot_operational_entrypoint",
    )


def test_ignored_importable_package_directory_fails_closed(tmp_path: Path):
    package = tmp_path / "src" / "shadow_package"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")

    runner = FakeRunner(ignored="src/shadow_package\n")
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.dirty_entries == (
        "IGNORED_IMPORTABLE_PACKAGE src/shadow_package",
    )


def test_ignored_pycache_bytecode_is_allowed(tmp_path: Path):
    runner = FakeRunner(
        ignored="src/ai_asset_platform/__pycache__/settings.cpython-313.pyc\n"
    )
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is True
    assert result.dirty_entries == ()


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


def test_human_wrapper_is_in_default_audited_paths():
    assert "live_pilot_operational_once.sh" in AUDITED_PATHS


def test_tracked_edit_in_human_wrapper_fails_closed(tmp_path: Path):
    runner = FakeRunner(status=" M live_pilot_operational_once.sh\n")
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=SHA,
        repository_root=tmp_path,
        now=NOW,
        runner=runner,
    )

    assert result.ready is False
    assert result.audited_paths_clean is False
    assert result.dirty_entries == (" M live_pilot_operational_once.sh",)


def test_human_wrapper_checks_source_gates_before_isolated_python_launch():
    source = Path("live_pilot_operational_once.sh").read_text(encoding="utf-8")
    cleanliness = source.index("git status --porcelain=v1 --untracked-files=all")
    index_hidden = source.index("git ls-files -v --")
    ignored_importable = source.index(
        "git ls-files --others --ignored --exclude-standard -- src tests scripts"
    )
    interpreter_attestation = source.index('TRUSTED_PYTHON_REAL="$(/usr/bin/readlink -f -- "$VENV_PYTHON_LINK")"')
    isolated_python = source.index('"$TRUSTED_PYTHON_REAL" -I -P -S -c "$PYTHON_BOOTSTRAP"')

    assert interpreter_attestation < isolated_python
    assert cleanliness < isolated_python
    assert index_hidden < isolated_python
    assert ignored_importable < isolated_python
    assert source.index('ACTUAL_SHA="$(git rev-parse HEAD)"') < isolated_python
    assert "\nsource .venv/bin/activate\n" not in source
    assert "bash scripts/ensure_exact_checkout_runtime.sh" not in source
