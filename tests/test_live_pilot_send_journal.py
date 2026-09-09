from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ai_asset_platform.execution.live_pilot_send_journal as journal
from ai_asset_platform.execution.live_pilot_send_journal import (
    create_consumed_authorization_journal,
    load_send_journal,
    mark_order_acknowledged,
    mark_postfill_proven,
    mark_unknown,
    record_send_attempt,
    send_attempt_permitted,
    send_attempt_recorded,
)

NOW = datetime(2026, 9, 6, 8, 0, 0, tzinfo=timezone.utc)
INTENT = "live-pilot:9432.T:BUY:100:20260907"
NONCE = "nonce_ABC-123"


@pytest.fixture(autouse=True)
def _isolated_canonical_journal_root(monkeypatch, tmp_path: Path):
    """Codex P1: the pilot-wide global marker now lives at a canonical path

    independent of any test's `directory=tmp_path` argument, by design (see
    _canonical_journal_root). Without this override, every test below would
    read/write the real repository's results/live_pilot_send_journal/
    GLOBAL_SEND_ATTEMPT.lock, leaking state across test runs and polluting a
    real checkout.
    """
    monkeypatch.setattr(
        journal, "_canonical_journal_root", lambda: tmp_path / "_canonical_root"
    )


def _consumed(**overrides) -> dict:
    payload = {"status": "CONSUMED", "intent_id": INTENT, "nonce": NONCE, "order_sent": False, "live_order_sent": False}
    payload.update(overrides)
    return payload


def _create(tmp_path: Path):
    return create_consumed_authorization_journal(intent_id=INTENT, nonce=NONCE, consumed_authorization=_consumed(), directory=tmp_path, now=NOW)


def test_unconsumed_or_mismatched_authorization_cannot_create_journal(tmp_path: Path):
    with pytest.raises(PermissionError, match="not been consumed"):
        create_consumed_authorization_journal(intent_id=INTENT, nonce=NONCE, consumed_authorization=_consumed(status="AUTHORIZED_ONCE"), directory=tmp_path, now=NOW)
    with pytest.raises(PermissionError, match="nonce mismatch"):
        create_consumed_authorization_journal(intent_id=INTENT, nonce=NONCE, consumed_authorization=_consumed(nonce="different"), directory=tmp_path, now=NOW)


def test_clean_consumed_authorization_allows_exactly_one_future_attempt(tmp_path: Path):
    created = _create(tmp_path)
    assert created["state"] == "AUTHORIZATION_CONSUMED"
    assert created["send_attempt_count"] == 0
    assert send_attempt_recorded(INTENT, directory=tmp_path) is False
    assert send_attempt_permitted(INTENT, directory=tmp_path) is True
    for key in ("automatic_resend_allowed", "automatic_cancel_allowed", "automatic_modify_allowed", "automatic_flatten_allowed", "automatic_close_allowed"):
        assert created[key] is False


def test_send_attempt_marker_is_exclusive_and_prevents_second_attempt(tmp_path: Path):
    _create(tmp_path)
    first = record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))
    assert first["state"] == "SEND_ATTEMPT_RECORDED"
    assert first["send_attempt_count"] == 1
    assert first["recovery_required"] is True
    assert send_attempt_recorded(INTENT, directory=tmp_path) is True
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False
    with pytest.raises(PermissionError, match="no longer permitted|already been spent"):
        record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=2))


def test_crash_after_irreversible_marker_still_blocks_all_resend(tmp_path: Path, monkeypatch):
    _create(tmp_path)
    def fail_summary_replace(*args, **kwargs):
        raise OSError("simulated crash after marker creation")
    monkeypatch.setattr(journal, "_atomic_replace", fail_summary_replace)
    with pytest.raises(OSError, match="simulated crash"):
        record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))
    assert send_attempt_recorded(INTENT, directory=tmp_path) is True
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False
    with pytest.raises(PermissionError, match="already been (spent|recorded)"):
        record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=2))


def test_unknown_state_never_reenables_automatic_action(tmp_path: Path):
    _create(tmp_path)
    record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))
    unknown = mark_unknown(INTENT, reason="socket disconnected before broker state was proven", directory=tmp_path, now=NOW + timedelta(seconds=2))
    assert unknown["state"] == "UNKNOWN"
    assert unknown["recovery_required"] is True
    for key in ("automatic_resend_allowed", "automatic_cancel_allowed", "automatic_modify_allowed", "automatic_flatten_allowed", "automatic_close_allowed"):
        assert unknown[key] is False
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False


def test_acknowledgement_requires_irreversible_attempt_marker(tmp_path: Path):
    _create(tmp_path)
    with pytest.raises(PermissionError, match="marker is missing"):
        mark_order_acknowledged(INTENT, order_id=101, perm_id=202, directory=tmp_path, now=NOW)


def test_acknowledged_order_can_transition_to_postfill_proven_without_resend(tmp_path: Path):
    _create(tmp_path)
    record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))
    acknowledged = mark_order_acknowledged(INTENT, order_id=101, perm_id=202, directory=tmp_path, now=NOW + timedelta(seconds=2))
    assert acknowledged["state"] == "ORDER_ACKNOWLEDGED"
    proven = mark_postfill_proven(INTENT, exec_id="exec-9432-001", order_id=101, perm_id=202, directory=tmp_path, now=NOW + timedelta(seconds=3))
    assert proven["state"] == "POSTFILL_PROVEN"
    assert proven["recovery_required"] is False
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False


def test_unknown_can_only_be_resolved_by_matching_read_only_postfill_identity(tmp_path: Path):
    _create(tmp_path)
    record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))
    mark_unknown(INTENT, reason="timeout", directory=tmp_path, now=NOW + timedelta(seconds=2))
    with pytest.raises(PermissionError, match="conflicts"):
        payload = load_send_journal(INTENT, directory=tmp_path)
        assert payload is not None
        payload["order_id"] = 101
        payload["perm_id"] = 202
        journal._atomic_replace(journal._path(INTENT, tmp_path), payload)
        mark_postfill_proven(INTENT, exec_id="exec-9432-001", order_id=999, perm_id=202, directory=tmp_path, now=NOW + timedelta(seconds=3))
    assert load_send_journal(INTENT, directory=tmp_path)["state"] == "UNKNOWN"
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False
    proven = mark_postfill_proven(INTENT, exec_id="exec-9432-001", order_id=101, perm_id=202, directory=tmp_path, now=NOW + timedelta(seconds=4))
    assert proven["state"] == "POSTFILL_PROVEN"
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False


def test_corrupt_journal_fails_closed_for_send_permission(tmp_path: Path):
    _create(tmp_path)
    path = next(tmp_path.glob("*.json"))
    path.write_text("not-json\n", encoding="utf-8")
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False


def test_second_intent_id_cannot_create_a_second_send_attempt(tmp_path: Path):
    """Codex P1: switching intent_id (e.g. after a restart) must not allow a

    second reachable transport attempt once one has already been recorded for
    this pilot campaign directory.
    """
    _create(tmp_path)
    record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))
    assert journal.global_send_attempt_recorded(directory=tmp_path) is True

    other_intent = "live-pilot:9432.T:BUY:100:restarted-attempt"
    created = create_consumed_authorization_journal(
        intent_id=other_intent,
        nonce="nonce-restart",
        consumed_authorization=_consumed(intent_id=other_intent, nonce="nonce-restart"),
        directory=tmp_path,
        now=NOW + timedelta(seconds=2),
    )
    assert created["state"] == "AUTHORIZATION_CONSUMED"
    assert send_attempt_permitted(other_intent, directory=tmp_path) is False
    with pytest.raises(PermissionError, match="pilot campaign"):
        record_send_attempt(other_intent, directory=tmp_path, now=NOW + timedelta(seconds=3))


def test_global_marker_is_canonical_and_ignores_a_different_journal_dir(tmp_path: Path):
    """Codex P1 (PR #280 finding, ported): the pilot-wide marker's location

    must not depend on the caller-supplied journal_dir (or, by extension, a
    restart from a different cwd). A second attempt using a *different*
    journal_dir than the first must still be blocked by the same singleton
    marker, not create a fresh one of its own.
    """
    first_dir = tmp_path / "run_one"
    second_dir = tmp_path / "a_completely_different_journal_dir"
    first_dir.mkdir()
    second_dir.mkdir()

    create_consumed_authorization_journal(
        intent_id=INTENT,
        nonce=NONCE,
        consumed_authorization=_consumed(),
        directory=first_dir,
        now=NOW,
    )
    record_send_attempt(INTENT, directory=first_dir, now=NOW + timedelta(seconds=1))
    assert journal.global_send_attempt_recorded(directory=first_dir) is True
    # The same canonical marker must also be visible when queried through an
    # entirely different (and never-before-used) journal_dir.
    assert journal.global_send_attempt_recorded(directory=second_dir) is True

    other_intent = "live-pilot:9432.T:BUY:100:different-journal-dir"
    created = create_consumed_authorization_journal(
        intent_id=other_intent,
        nonce="nonce-elsewhere",
        consumed_authorization=_consumed(intent_id=other_intent, nonce="nonce-elsewhere"),
        directory=second_dir,
        now=NOW + timedelta(seconds=2),
    )
    assert created["state"] == "AUTHORIZATION_CONSUMED"
    assert send_attempt_permitted(other_intent, directory=second_dir) is False
    with pytest.raises(PermissionError, match="pilot campaign"):
        record_send_attempt(other_intent, directory=second_dir, now=NOW + timedelta(seconds=3))


def test_mkdir_durable_fsyncs_every_newly_created_ancestor(tmp_path: Path, monkeypatch):
    """Codex P1 (PR #280 finding, ported): the very first pilot run creates

    results/live_pilot_send_journal/ (and, here, its own missing parents)
    from scratch. Each newly created directory's own parent must be
    fsynced, not only the innermost one, or a power loss right after
    creation could lose the entire new directory tree.
    """
    calls = []
    original = journal._fsync_parent_dir

    def spy(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(journal, "_fsync_parent_dir", spy)
    target = tmp_path / "a" / "b" / "c"
    journal._mkdir_durable(target)

    assert target.is_dir()
    fsynced_parents = {call.parent for call in calls}
    fsynced_children = {call for call in calls}
    # Every newly created directory (a, a/b, a/b/c) must have had its own
    # parent fsynced.
    assert (tmp_path / "a") in fsynced_children
    assert (tmp_path / "a" / "b") in fsynced_children
    assert (tmp_path / "a" / "b" / "c") in fsynced_children
    assert tmp_path in fsynced_parents
    assert (tmp_path / "a") in fsynced_parents
    assert (tmp_path / "a" / "b") in fsynced_parents

    # A second call against an already-fully-created directory must not
    # attempt to fsync anything (nothing new was created).
    calls.clear()
    journal._mkdir_durable(target)
    assert calls == []


def test_global_marker_directory_entry_is_fsynced(tmp_path: Path, monkeypatch):
    calls = []
    original = journal._fsync_parent_dir

    def spy(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(journal, "_fsync_parent_dir", spy)
    _create(tmp_path)
    record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))
    assert len(calls) >= 2
    # The per-intent marker's directory entry (under the caller's directory)
    # and the canonical global marker's directory entry (under the isolated
    # canonical root from the autouse fixture) must both be fsynced.
    assert any(call.parent == tmp_path for call in calls)
    assert any(call.parent == journal._canonical_journal_root() for call in calls)


def test_write_full_loops_over_short_writes_and_rejects_no_progress(tmp_path: Path, monkeypatch):
    """Codex P1 (round 4): a short ``os.write`` must not silently persist a

    truncated durable marker; the helper must loop until every byte is
    written and fail rather than fsync/rename on no-progress writes.
    """
    import os

    data = b"y" * 100
    target = tmp_path / "short_write_target.bin"
    original_write = os.write

    def short_write(fd, chunk):
        return original_write(fd, chunk[:7])

    monkeypatch.setattr(os, "write", short_write)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        journal._write_full(descriptor, data)
    finally:
        os.close(descriptor)
    assert target.read_bytes() == data

    zero_progress_target = tmp_path / "zero_progress.bin"
    monkeypatch.setattr(os, "write", lambda fd, chunk: 0)
    descriptor = os.open(zero_progress_target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with pytest.raises(OSError, match="no progress"):
            journal._write_full(descriptor, data)
    finally:
        os.close(descriptor)


def test_is_exact_int_rejects_coerced_types():
    assert journal._is_exact_int(1, 1) is True
    assert journal._is_exact_int(0, 0) is True
    assert journal._is_exact_int(1.0, 1) is False
    assert journal._is_exact_int("1", 1) is False
    assert journal._is_exact_int(True, 1) is False
    assert journal._is_exact_int(False, 0) is False


def test_malformed_send_attempt_count_fails_closed_for_state_transitions(tmp_path: Path):
    """PM P2 (round 9): record_send_attempt, mark_unknown, and

    mark_postfill_proven must reject a coerced (float/string/boolean)
    persisted send_attempt_count instead of letting int(...) accept it.
    """
    _create(tmp_path)
    record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))

    path = journal._path(INTENT, tmp_path)
    payload = load_send_journal(INTENT, directory=tmp_path)
    payload["send_attempt_count"] = 1.0
    journal._atomic_replace(path, payload)

    with pytest.raises(PermissionError, match="single recorded send attempt"):
        mark_postfill_proven(
            INTENT,
            exec_id="exec-1",
            order_id=101,
            perm_id=202,
            directory=tmp_path,
            now=NOW + timedelta(seconds=2),
        )
    with pytest.raises(PermissionError, match="single send attempt"):
        mark_unknown(INTENT, reason="timeout", directory=tmp_path, now=NOW + timedelta(seconds=2))


def test_module_contains_no_broker_transport_or_automatic_recovery_action():
    source = Path("src/ai_asset_platform/execution/live_pilot_send_journal.py").read_text(encoding="utf-8")
    forbidden = (".placeOrder(", ".cancelOrder(", "reqOpenOrders(", "reqAllOpenOrders(", "reqExecutions(", "enable_live_trading = True", "automatic_resend_allowed=True", "automatic_cancel_allowed=True", "automatic_modify_allowed=True", "automatic_flatten_allowed=True", "automatic_close_allowed=True")
    for token in forbidden:
        assert token not in source
