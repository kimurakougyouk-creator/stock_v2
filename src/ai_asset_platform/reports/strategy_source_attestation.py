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
    "signal_runner.py",
    "config.py",
    "requirements.txt",
    "pyproject.toml",
    "pytest.ini",
    "start.sh",
    "scripts/run.sh",
    "ibkr_strategy_profitability_evidence_once.sh",
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
    return result.actual_commit_sha
