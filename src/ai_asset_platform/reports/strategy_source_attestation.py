"""Fail-closed source attestation for natural Paper strategy evidence.

This reuses the repository's hardened tracked/untracked/index-hidden/ignored
source audit. It never connects to a broker and never authorizes Live trading.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Callable

from ai_asset_platform.execution.live_pilot_source_cutover import (
    audit_live_pilot_source_cutover,
)


STRATEGY_AUDITED_PATHS: tuple[str, ...] = (
    "src",
    "ai_asset_platform",
    "ai_asset_platform.py",
    "signal_runner.py",
    "config.py",
    "requirements.txt",
    "pyproject.toml",
    "pytest.ini",
    "start.sh",
    "scripts/run.sh",
    "scripts/verify_strategy_source_clean.sh",
    "scripts/ensure_exact_checkout_runtime.sh",
    "scripts/verify_exact_checkout_import.py",
    "ibkr_verified_paper_runtime_once.sh",
    "ibkr_strategy_profitability_evidence_once.sh",
    "strategy_promotion_policy_once.sh",
    "config",
    "sitecustomize.py",
    "sitecustomize.pyc",
    "usercustomize.py",
    "usercustomize.pyc",
)


class StrategySourceAttestationError(RuntimeError):
    """Raised when exact strategy source cleanliness cannot be proven."""


def attest_strategy_source(
    expected_sha: str,
    *,
    repository_root: Path = Path("."),
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    result = audit_live_pilot_source_cutover(
        expected_commit_sha=expected_sha,
        repository_root=repository_root,
        audited_paths=STRATEGY_AUDITED_PATHS,
        runner=runner,
    )
    if not result.ready or result.actual_commit_sha is None:
        detail = ", ".join(result.dirty_entries) or "source SHA mismatch"
        raise StrategySourceAttestationError(
            f"strategy source attestation blocked: {detail}"
        )

    # Strategy evidence/runtime attestation is stricter than the reusable Live
    # source-cutover audit: executable ignored bytecode caches are not trusted.
    # A timestamp-valid .pyc can otherwise execute bytes that are absent from
    # the attested commit even when tracked source is clean.
    try:
        ignored = runner(
            [
                "git",
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--",
                *STRATEGY_AUDITED_PATHS,
            ],
            cwd=str(repository_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StrategySourceAttestationError(
            "strategy source attestation blocked: ignored-cache audit failed"
        ) from exc
    ignored_cache_entries = tuple(
        line.strip()
        for line in str(ignored.stdout or "").splitlines()
        if "/__pycache__/" in f"/{line.strip().replace(chr(92), '/')}"
        and line.strip().lower().endswith((".pyc", ".pyo"))
    )
    if ignored_cache_entries:
        detail = ", ".join(
            f"IGNORED_EXECUTABLE_CACHE {entry}" for entry in ignored_cache_entries
        )
        raise StrategySourceAttestationError(
            f"strategy source attestation blocked: {detail}"
        )
    return result.actual_commit_sha
