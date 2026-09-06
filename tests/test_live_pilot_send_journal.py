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


def _consumed(**overrides) -> dict:
    payload = {
        "status": "CONSUMED",
        "intent_id": INTENT,
        "nonce": NONCE,
        "order_sent": False,
        "live_order_sent": False,
    }
    payload.update(overrides)
    return payload


def _create(tmp_path: Path):
    return create_consumed_authorization_journal(
        intent_id=INTENT,
        nonce=NONCE,
        consumed_authorization=_consumed(),
        directory=tmp_path,
        now=NOW,
    )


def test_unconsumed_or_mismatched_authorization_cannot_create_journal(tmp_path: Path):
    with pytest.raises(PermissionError, match="not been consumed"):
        create_consumed_authorization_journal(
            intent_id=INTENT,
            nonce=NONCE,
            consumed_authorization=_consumed(status="AUTHORIZED_ONCE"),
            directory=tmp_path,
            now=NOW,
        )

    with pytest.raises(PermissionError, match="nonce mismatch"):
        create_consumed_authorization_journal(
            intent_id=INTENT,
            nonce=NONCE,
            consumed_authorization=_consumed(nonce="different"),
            directory=tmp_path,
            now=NOW,
        )


def test_clean_consumed_authorization_allows_exactly_one_future_attempt(tmp_path: Path):
    created = _create(tmp_path)

    assert created["state"] == "AUTHORIZATION_CONSUMED"
    assert created["send_attempt_count"] == 0
    assert send_attempt_recorded(INTENT, directory=tmp_path) is False
    assert send_attempt_permitted(INTENT, directory=tmp_path) is True
    for key in (
        "automatic_resend_allowed",
        "automatic_cancel_allowed",
        "automatic_modify_allowed",
        "automatic_flatten_allowed",
        "automatic_close_allowed",
    ):
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

    with pytest.raises(PermissionError, match="already been spent"):
        record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=2))


def test_unknown_state_never_reenables_automatic_action(tmp_path: Path):
    _create(tmp_path)
    record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))

    unknown = mark_unknown(
        INTENT,
        reason="socket disconnected before broker state was proven",
        directory=tmp_path,
        now=NOW + timedelta(seconds=2),
    )
    assert unknown["state"] == "UNKNOWN"
    assert unknown["recovery_required"] is True
    for key in (
        "automatic_resend_allowed",
        "automatic_cancel_allowed",
        "automatic_modify_allowed",
        "automatic_flatten_allowed",
        "automatic_close_allowed",
    ):
        assert unknown[key] is False
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False


def test_acknowledgement_requires_irreversible_attempt_marker(tmp_path: Path):
    _create(tmp_path)

    with pytest.raises(PermissionError, match="marker is missing"):
        mark_order_acknowledged(
            INTENT,
            order_id=101,
            perm_id=202,
            directory=tmp_path,
            now=NOW,
        )


def test_acknowledged_order_can_transition_to_postfill_proven_without_resend(tmp_path: Path):
    _create(tmp_path)
    record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))
    acknowledged = mark_order_acknowledged(
        INTENT,
        order_id=101,
        perm_id=202,
        directory=tmp_path,
        now=NOW + timedelta(seconds=2),
    )
    assert acknowledged["state"] == "ORDER_ACKNOWLEDGED"

    proven = mark_postfill_proven(
        INTENT,
        exec_id="exec-9432-001",
        order_id=101,
        perm_id=202,
        directory=tmp_path,
        now=NOW + timedelta(seconds=3),
    )
    assert proven["state"] == "POSTFILL_PROVEN"
    assert proven["recovery_required"] is False
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False


def test_unknown_can_only_be_resolved_by_matching_read_only_postfill_identity(tmp_path: Path):
    _create(tmp_path)
    record_send_attempt(INTENT, directory=tmp_path, now=NOW + timedelta(seconds=1))
    mark_unknown(
        INTENT,
        reason="timeout",
        directory=tmp_path,
        now=NOW + timedelta(seconds=2),
    )

    with pytest.raises(PermissionError, match="conflicts"):
        payload = load_send_journal(INTENT, directory=tmp_path)
        assert payload is not None
        payload["order_id"] = 101
        payload["perm_id"] = 202
        journal._atomic_replace(journal._path(INTENT, tmp_path), payload)
        mark_postfill_proven(
            INTENT,
            exec_id="exec-9432-001",
            order_id=999,
            perm_id=202,
            directory=tmp_path,
            now=NOW + timedelta(seconds=3),
        )

    assert load_send_journal(INTENT, directory=tmp_path)["state"] == "UNKNOWN"
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False

    proven = mark_postfill_proven(
        INTENT,
        exec_id="exec-9432-001",
        order_id=101,
        perm_id=202,
        directory=tmp_path,
        now=NOW + timedelta(seconds=4),
    )
    assert proven["state"] == "POSTFILL_PROVEN"
    assert send_attempt_permitted(INTENT, directory=tmp_path) is False


def test_corrupt_journal_fails_closed_for_send_permission(tmp_path: Path):
    _create(tmp_path)
    path = next(tmp_path.glob("*.json"))
    path.write_text("not-json\n", encoding="utf-8")

    assert send_attempt_permitted(INTENT, directory=tmp_path) is False


def test_module_contains_no_broker_transport_or_automatic_recovery_action():
    source = Path(
        "src/ai_asset_platform/execution/live_pilot_send_journal.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "reqOpenOrders(",
        "reqAllOpenOrders(",
        "reqExecutions(",
        "enable_live_trading = True",
        "automatic_resend_allowed=True",
        "automatic_cancel_allowed=True",
        "automatic_modify_allowed=True",
        "automatic_flatten_allowed=True",
        "automatic_close_allowed=True",
    )
    for token in forbidden:
        assert token not in source
