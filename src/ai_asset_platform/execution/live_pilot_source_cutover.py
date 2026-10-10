"""Fail-closed source/PIN verification for a future Live pilot runtime.

This module proves that the locally executed safety-critical source is exactly at
one externally approved Git commit and has no tracked or untracked changes in the
audited code paths.  Runtime result/evidence files are deliberately outside the audited
pathspec because they are expected to change during operation.

The expected commit SHA must come from an independently approved GitHub source
freeze record.  This module does not choose or approve a commit itself.

No broker connection or order API exists here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
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
    "live_pilot_operational_once.sh",
    "live_pilot_operational_once.ps1",
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
SAFE_GIT_PREFIX: tuple[str, ...] = (
    "/usr/bin/git",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
)
# Windows has no equivalent of a root-owned, non-group/world-writable
# /usr/bin: a bare `git` resolved via PATH could be shadowed by an
# attacker-controlled executable earlier on PATH. Windows' own default ACLs
# make %ProgramFiles%/%ProgramFiles(x86)% non-writable by a standard user
# account (only Administrators/SYSTEM have write access) -- the same
# property /usr/bin's root ownership provides on POSIX -- so the trusted
# Git executable is resolved to one of Git for Windows' default
# Program-Files install locations and verified to actually live under one
# of those roots (and not be a symlink/junction redirecting elsewhere)
# before being trusted, rather than searched for via PATH.
_WINDOWS_GIT_CANDIDATES: tuple[str, ...] = (
    r"Git\cmd\git.exe",
    r"Git\bin\git.exe",
    r"Git\mingw64\bin\git.exe",
)


def _windows_admin_only_roots() -> tuple[Path, ...]:
    # Codex P1: os.environ["ProgramFiles"] is just an environment variable,
    # not an OS-owned fact -- a hostile inherited environment could redefine
    # it to point at any user-writable directory. Read the same value from
    # its registry source of truth instead (HKLM, admin-only-writable,
    # cannot be influenced by this process's environment).
    import winreg

    roots = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion",
        ) as key:
            for value_name in ("ProgramFilesDir", "ProgramFilesDir (x86)"):
                try:
                    value, _ = winreg.QueryValueEx(key, value_name)
                except FileNotFoundError:
                    continue
                if value:
                    roots.append(Path(value).resolve())
    except OSError as exc:
        raise OSError(f"Program Files registry roots could not be read: {exc}") from exc
    if not roots:
        raise OSError("no Program Files root could be determined from the registry")
    return tuple(roots)


def _resolve_trusted_git_windows() -> str:
    for root in _windows_admin_only_roots():
        for suffix in _WINDOWS_GIT_CANDIDATES:
            candidate = root / suffix
            if not candidate.is_file():
                continue
            if candidate.is_symlink():
                continue
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if resolved != candidate:
                continue
            if not any(_is_relative_to(resolved, r) for r in _windows_admin_only_roots()):
                continue
            return str(resolved)
    raise OSError(
        "no trusted admin-only-writable Git executable found under "
        "%ProgramFiles%/%ProgramFiles(x86)%; install Git for Windows to its "
        "default location"
    )


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True


REPORT_SCHEMA_VERSION = 1


def safe_git_command(*args: str) -> list[str]:
    """Build a Git command with repo-configured executable hooks disabled."""
    if sys.platform == "win32":
        git_exe = _resolve_trusted_git_windows()
        prefix: tuple[str, ...] = (
            git_exe,
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
        )
    else:
        prefix = SAFE_GIT_PREFIX
    return [*prefix, *args]
_IMPORTABLE_IGNORED_SUFFIXES = (".py", ".pyc", ".pyo", ".pyz", ".so", ".pyd", ".dylib")


def _index_hidden_entries(raw_listing: str) -> tuple[str, ...]:
    entries: list[str] = []
    for raw in raw_listing.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        tag = line[0]
        if tag == "S" or tag.islower():
            entries.append(f"INDEX_HIDDEN {line}")
    return tuple(entries)


def _ignored_importable_entries(
    raw_listing: str,
    *,
    repository_root: Path,
) -> tuple[str, ...]:
    entries: list[str] = []
    for raw in raw_listing.splitlines():
        path = raw.strip()
        if not path:
            continue
        normalized = path.replace("\\", "/")
        candidate = repository_root / path

        # An extensionless symlink can still be importable when it points at a
        # package directory. Never follow/trust ignored symlinks in audited
        # source paths.
        if candidate.is_symlink():
            entries.append(f"IGNORED_SYMLINK {path}")
            continue

        if "/__pycache__/" in f"/{normalized}":
            continue
        if normalized.lower().endswith(_IMPORTABLE_IGNORED_SUFFIXES):
            entries.append(f"IGNORED_IMPORTABLE {path}")
            continue

        # git ls-files normally emits files, but fail closed if a directory
        # entry is returned and it already looks like an importable package.
        if candidate.is_dir():
            try:
                names = tuple(child.name.lower() for child in candidate.iterdir())
            except OSError:
                entries.append(f"IGNORED_PACKAGE_UNREADABLE {path}")
                continue
            if (
                "__init__.py" in names
                or "__init__.pyc" in names
                or any(
                    name.startswith("__init__") and name.endswith(".so")
                    for name in names
                )
            ):
                entries.append(f"IGNORED_IMPORTABLE_PACKAGE {path}")
    return tuple(entries)


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


_GIT_DISCOVERY_ENV_VARS: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def sanitized_git_env() -> dict[str, str]:
    """A copy of the environment with Git repository-discovery variables removed.

    A hostile GIT_DIR/GIT_WORK_TREE (etc.) could make every check below
    inspect a different, clean repository while the actual checkout this
    process later imports source from (``repository_root``/``cwd``) remains
    whatever an attacker left it as. Discovery must be forced to ``cwd``
    alone, never influenced by inherited environment.
    """
    env = dict(os.environ)
    for name in _GIT_DISCOVERY_ENV_VARS:
        env.pop(name, None)
    return env


def _run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    completed = runner(
        safe_git_command("-C", str(cwd), *args),
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env=sanitized_git_env(),
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
    """Verify exact approved commit plus tracked/untracked cleanliness of audited code paths."""
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
                "--untracked-files=all",
                "--",
                *normalized_paths,
            ),
            cwd=repository_root,
            runner=runner,
        )
        index_text = _run_git(
            (
                "ls-files",
                "-v",
                "--",
                *normalized_paths,
            ),
            cwd=repository_root,
            runner=runner,
        )
        ignored_text = _run_git(
            (
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--",
                *normalized_paths,
            ),
            cwd=repository_root,
            runner=runner,
        )
        dirty_entries = (
            tuple(
                line.rstrip() for line in status_text.splitlines() if line.strip()
            )
            + _index_hidden_entries(index_text)
            + _ignored_importable_entries(
                ignored_text,
                repository_root=repository_root,
            )
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
            "approved Git commit and has no tracked/untracked changes or ignored importable artifacts/packages/symlinks in safety-critical paths. "
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
