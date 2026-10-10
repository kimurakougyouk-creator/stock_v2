"""Tests for scripts/issue_live_pilot_authorization_cli.py.

This CLI exists so the Windows and POSIX operational wrappers can issue a
fresh authorization and capture its internally-generated nonce without the
operator ever seeing or transcribing it.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "issue_live_pilot_authorization_cli.py"

FINGERPRINT = "a" * 64


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(CLI), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _base_args(auth_dir: Path) -> list[str]:
    return [
        "--confirmation=AUTHORIZE_ONE_LIVE_PILOT_ONLY",
        "--intent-id=test-intent",
        "--ticker=9432.T",
        "--side=BUY",
        "--quantity=100",
        "--limit-price=172.7",
        "--estimated-notional-jpy=17270",
        f"--account-fingerprint={FINGERPRINT}",
        "--endpoint-port=7496",
        f"--authorization-dir={auth_dir}",
    ]


def test_prints_only_the_nonce_on_success(tmp_path: Path):
    auth_dir = tmp_path / "auth"
    result = _run(_base_args(auth_dir), cwd=REPO_ROOT)

    assert result.returncode == 0, result.stderr
    assert result.stdout
    assert "\n" not in result.stdout
    assert result.stderr == ""


def test_issued_authorization_is_bound_to_the_exact_parameters(tmp_path: Path):
    from ai_asset_platform.execution.live_pilot_one_shot_authorization import (
        consume_live_pilot_authorization,
    )

    auth_dir = tmp_path / "auth"
    result = _run(_base_args(auth_dir), cwd=REPO_ROOT)
    assert result.returncode == 0, result.stderr
    nonce = result.stdout

    consumed = consume_live_pilot_authorization(
        nonce=nonce,
        intent_id="test-intent",
        ticker="9432.T",
        side="BUY",
        quantity=100,
        limit_price=172.7,
        estimated_notional_jpy=17270,
        account_fingerprint=FINGERPRINT,
        endpoint_port=7496,
        authorization_dir=auth_dir,
    )
    assert consumed["nonce"] == nonce


def test_blocks_on_wrong_confirmation_value(tmp_path: Path):
    auth_dir = tmp_path / "auth"
    args = _base_args(auth_dir)
    args[0] = "--confirmation=WRONG_VALUE"
    result = _run(args, cwd=REPO_ROOT)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "BLOCKED" in result.stderr


def test_blocks_on_invalid_endpoint_port(tmp_path: Path):
    auth_dir = tmp_path / "auth"
    args = _base_args(auth_dir)
    args[8] = "--endpoint-port=9999"
    result = _run(args, cwd=REPO_ROOT)

    assert result.returncode == 2
    assert result.stdout == ""


def test_blocks_on_missing_required_argument(tmp_path: Path):
    auth_dir = tmp_path / "auth"
    args = [a for a in _base_args(auth_dir) if not a.startswith("--side=")]
    result = _run(args, cwd=REPO_ROOT)

    assert result.returncode != 0
    assert result.stdout == ""
