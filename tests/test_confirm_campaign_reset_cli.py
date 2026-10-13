"""Tests for scripts/confirm_campaign_reset_cli.py.

This CLI exists so an operator can advance the Live pilot campaign to a new
generation from a single, explicit, auditable command. The underlying
confirm_campaign_reset safety contract (wrong confirmation, empty reason,
no-attempt-yet, already-reconciled) is exercised thoroughly in
tests/test_live_pilot_send_journal.py; these tests cover only the CLI's own
argument handling and success/failure output framing, via in-process
monkeypatching of confirm_campaign_reset itself -- the real function's
generation pointer/lock paths deliberately ignore any caller-supplied
directory (see confirm_campaign_reset's own docstring), so calling it for
real here would touch the real machine-state root, exactly like
test_issue_live_pilot_authorization_cli.py's identical constraint.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

CLI = Path(__file__).resolve().parents[1] / "scripts" / "confirm_campaign_reset_cli.py"

_SPEC = importlib.util.spec_from_file_location("confirm_campaign_reset_cli", CLI)
cli_module = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = cli_module
_SPEC.loader.exec_module(cli_module)


def test_success_prints_the_reset_record_as_json(monkeypatch, capsys):
    record = {
        "schema_version": 1,
        "reset_id": "abc123",
        "prior_generation": 1,
        "new_generation": 2,
        "prior_generation_stuck_intent_id": "live-pilot-9432T-2026-10-13",
        "prior_generation_stuck_state": "UNKNOWN",
        "reason": "2026-10-13 pilot UNKNOWN, immutable proof unrecoverable",
        "confirmed_at": "2026-10-13T06:00:00+00:00",
        "automatic": False,
    }
    seen = {}

    def _fake_confirm_campaign_reset(**kwargs):
        seen.update(kwargs)
        return record

    monkeypatch.setattr(
        cli_module, "confirm_campaign_reset", _fake_confirm_campaign_reset
    )

    exit_code = cli_module.main(
        [
            "--confirmation", "RESET_LIVE_PILOT_CAMPAIGN_AFTER_UNRECOVERABLE_UNKNOWN",
            "--reason", "2026-10-13 pilot UNKNOWN, immutable proof unrecoverable",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert seen["confirmation"] == "RESET_LIVE_PILOT_CAMPAIGN_AFTER_UNRECOVERABLE_UNKNOWN"
    assert seen["reason"] == "2026-10-13 pilot UNKNOWN, immutable proof unrecoverable"
    assert "directory" not in seen
    assert '"new_generation": 2' in captured.out
    assert captured.err == ""


def test_journal_dir_flag_is_forwarded_as_directory(monkeypatch, tmp_path):
    seen = {}

    def _fake_confirm_campaign_reset(**kwargs):
        seen.update(kwargs)
        return {"reset_id": "x"}

    monkeypatch.setattr(
        cli_module, "confirm_campaign_reset", _fake_confirm_campaign_reset
    )

    exit_code = cli_module.main(
        [
            "--confirmation", "RESET_LIVE_PILOT_CAMPAIGN_AFTER_UNRECOVERABLE_UNKNOWN",
            "--reason", "test reason",
            "--journal-dir", str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert seen["directory"] == tmp_path


def test_failure_prints_blocked_to_stderr_and_exits_nonzero(monkeypatch, capsys):
    def _fake_confirm_campaign_reset(**kwargs):
        raise PermissionError("exact campaign-reset operator confirmation is missing")

    monkeypatch.setattr(
        cli_module, "confirm_campaign_reset", _fake_confirm_campaign_reset
    )

    exit_code = cli_module.main(
        ["--confirmation", "WRONG", "--reason", "test reason"]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert "BLOCKED" in captured.err
    assert "confirmation is missing" in captured.err


def test_missing_required_argument_fails_without_calling_reset(monkeypatch):
    monkeypatch.setattr(
        cli_module,
        "confirm_campaign_reset",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("confirm_campaign_reset must not be called")
        ),
    )

    try:
        cli_module.main(["--confirmation", "X"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("argparse should have exited for a missing --reason")
