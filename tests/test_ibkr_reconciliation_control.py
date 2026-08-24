from pathlib import Path

import pytest

from ai_asset_platform.execution.ibkr_reconciliation_control import (
    ReconciliationControlError,
    acquire_reconciliation_pause,
    load_reconciliation_exclusions,
    record_reconciliation_exclusions,
    reconciliation_is_paused,
    release_reconciliation_pause,
)


def test_pause_is_exclusive_and_owner_checked(tmp_path: Path):
    path = tmp_path / "pause.lock"
    pause = acquire_reconciliation_pause("owner-a", path=path)
    assert reconciliation_is_paused(path=path)
    with pytest.raises(ReconciliationControlError):
        acquire_reconciliation_pause("owner-b", path=path)
    release_reconciliation_pause(pause)
    assert not path.exists()


def test_exclusion_registry_is_idempotent(tmp_path: Path):
    path = tmp_path / "excluded.jsonl"
    first = record_reconciliation_exclusions(
        ["exec-2", "exec-1", "exec-1"],
        symbol="AAPL",
        reason="reset",
        order_intent_id="intent",
        path=path,
    )
    second = record_reconciliation_exclusions(
        ["exec-1"],
        symbol="AAPL",
        reason="reset",
        order_intent_id="intent",
        path=path,
    )
    assert first == ("exec-1", "exec-2")
    assert second == ("exec-1",)
    assert load_reconciliation_exclusions(path=path) == {"exec-1", "exec-2"}
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_invalid_exclusion_registry_fails_closed(tmp_path: Path):
    path = tmp_path / "excluded.jsonl"
    path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(ReconciliationControlError):
        load_reconciliation_exclusions(path=path)


def test_exclusion_requires_exec_id(tmp_path: Path):
    with pytest.raises(ReconciliationControlError):
        record_reconciliation_exclusions(
            [], symbol="AAPL", reason="reset", order_intent_id="intent",
            path=tmp_path / "excluded.jsonl",
        )
