"""Tests for scripts/issue_live_pilot_authorization_cli.py.

This CLI exists so the Windows and POSIX operational wrappers can issue a
fresh authorization and capture its internally-generated nonce without the
operator ever seeing or transcribing it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "issue_live_pilot_authorization_cli.py"

FINGERPRINT = "a" * 64

# Loaded by path (not a package) to call main() in-process for the
# recovery-path test below, which needs to monkeypatch
# global_send_attempt_recorded/load_send_journal -- impossible across the
# subprocess boundary the other tests in this file use, and global_send_
# attempt_recorded's real implementation deliberately ignores any caller-
# supplied directory (it always resolves the one true machine-state root),
# so it cannot be redirected to a tmp_path via an env var either.
_SPEC = importlib.util.spec_from_file_location("issue_live_pilot_authorization_cli", CLI)
cli_module = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = cli_module
_SPEC.loader.exec_module(cli_module)


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


def test_recovery_run_loads_the_durable_nonce_instead_of_issuing_a_fresh_one(
    tmp_path, monkeypatch, capsys
):
    # Codex P1 (PR #341 review): the operational entrypoint's recovery/
    # reconciliation path (_request_matches_durable_authorization) requires
    # the *consumed* nonce already recorded in the send journal from the
    # real attempt, not a new one -- a fresh nonce can never match, which
    # would silently break UNKNOWN/partial/rejected reconciliation after a
    # real attempt. When a prior Live pilot send attempt has already been
    # recorded, this CLI must load and print that durable nonce instead of
    # issuing anything new.
    durable_nonce = "durable-nonce-from-a-real-prior-attempt"
    monkeypatch.setattr(cli_module, "global_send_attempt_recorded", lambda **_: True)
    monkeypatch.setattr(
        cli_module,
        "load_send_journal",
        lambda intent_id, **_: {"intent_id": intent_id, "nonce": durable_nonce},
    )

    auth_dir = tmp_path / "auth"
    exit_code = cli_module.main(_base_args(auth_dir))
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == durable_nonce
    assert not auth_dir.exists(), "recovery must not issue (write) a new authorization"


def test_recovery_run_fails_closed_when_durable_nonce_is_unavailable(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli_module, "global_send_attempt_recorded", lambda **_: True)
    monkeypatch.setattr(cli_module, "load_send_journal", lambda intent_id, **_: None)

    auth_dir = tmp_path / "auth"
    exit_code = cli_module.main(_base_args(auth_dir))
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert "BLOCKED" in captured.err
