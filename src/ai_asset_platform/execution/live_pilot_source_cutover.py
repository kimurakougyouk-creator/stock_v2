"""Fail-closed source/PIN verification for a future Live pilot runtime.

This module proves that the locally executed safety-critical source is exactly at
one externally approved Git commit and has no tracked edits in the audited code
paths.  Runtime result/evidence files are deliberately outside the audited
pathspec because they are expected to change during operation.

The expected commit SHA must come from an independently approved GitHub source
freeze record.  This module does not choose or approve a commit itself.

No broker connection or order API exists here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from typing import Callable, Sequence


DEFAULT_REPORT_PATH = Path("results/live_pilot_source_cutover_latest.json")
AUDITED_PATHS: tuple[str, ...] = (
    "src",
    "tests",
    "scripts",
    "requirements.txt",
    "pyproject.toml",
    "pytest.ini",
    ".github/workflows/pytest.yml",
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LivePilotSourceCutover:
    status: str
    checked_at: str
    expected_commit_sha: str
    actual_commit_sha: str | None
    exact_commit_match: bool
    audited_paths_clean: bool
    dirty_entries: tuple[str, ...]
    ready: bool
    broker_connection_used: bool = False
    order_sent: bool = False
    live_order_sent: bool = False


def _utc_now(value: datetime | None) -> datetime:
    current = value if value is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("source-cutover clock must be timezone-aware")
    return current.astimezone(timezone.utc)


def _run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    completed = runner(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return str(completed.stdout or "")


def audit_live_pilot_source_cutover(
    *,
    expected_commit_sha: str,
    repository_root: Path = Path("."),
    audited_paths: Sequence[str] = AUDITED_PATHS,
    now: datetime | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> LivePilotSourceCutover:
    """Verify exact approved commit plus tracked cleanliness of audited code paths."""
    current = _utc_now(now)
    expected = str(expected_commit_sha or "").strip().lower()
    if not _SHA_RE.fullmatch(expected):
        raise ValueError("expected_commit_sha must be an exact 40-character Git SHA")
    normalized_paths = tuple(str(path).strip() for path in audited_paths if str(path).strip())
    if not normalized_paths:
        raise ValueError("at least one audited source path is required")

    actual: str | None = None
    dirty_entries: tuple[str, ...] = ()
    try:
        actual_text = _run_git(
            ("rev-parse", "HEAD"),
            cwd=repository_root,
            runner=runner,
        ).strip().lower()
        if _SHA_RE.fullmatch(actual_text):
            actual = actual_text

        status_text = _run_git(
            (
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
                "--",
                *normalized_paths,
            ),
            cwd=repository_root,
            runner=runner,
        )
        dirty_entries = tuple(
            line.rstrip() for line in status_text.splitlines() if line.strip()
        )
    except (OSError, subprocess.SubprocessError):
        # Any inability to prove source identity/cleanliness fails closed.
        actual = None
        dirty_entries = ("GIT_AUDIT_FAILED",)

    exact_match = actual == expected
    paths_clean = not dirty_entries
    ready = bool(exact_match and paths_clean)
    return LivePilotSourceCutover(
        status="READY_FOR_PINNED_RUNTIME" if ready else "BLOCKED",
        checked_at=current.isoformat(timespec="seconds"),
        expected_commit_sha=expected,
        actual_commit_sha=actual,
        exact_commit_match=exact_match,
        audited_paths_clean=paths_clean,
        dirty_entries=dirty_entries,
        ready=ready,
    )


def source_cutover_record(result: LivePilotSourceCutover) -> dict:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        **asdict(result),
        "audited_paths": list(AUDITED_PATHS),
        "interpretation": (
            "READY proves only that the audited local source equals the externally "
            "approved Git commit and has no tracked edits in safety-critical paths. "
            "It does not authorize or transmit a Live order."
        ),
    }


def persist_live_pilot_source_cutover(
    result: LivePilotSourceCutover,
    *,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(source_cutover_record(result), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)
