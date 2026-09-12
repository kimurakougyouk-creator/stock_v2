"""Durable fail-closed no-resend journal for one future Live pilot.

A future sender must persist an exclusive SEND_ATTEMPT marker *before* calling
any broker order API.  The marker, not the mutable summary journal, is the
irreversible source of truth for whether the single allowed transmission attempt
has already been spent.  A crash after marker creation therefore still blocks
all later sends.

Timeout, disconnect, exceptions, and any ambiguous outcome transition to
UNKNOWN and require read-only broker recovery.  This module has no broker
connection and no order API.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re


DEFAULT_JOURNAL_DIR = Path("results/live_pilot_send_journal")
REPORT_SCHEMA_VERSION = 2
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")

# This filename is deliberately fixed and does not vary with intent_id. It is
# the exclusive, pilot-campaign-wide no-resend marker: a caller cannot defeat
# the single-attempt guarantee by restarting under a new intent_id/nonce, since
# every such attempt must create this same marker before any per-intent state.
CAMPAIGN_ATTEMPT_FILENAME = "LIVE_PILOT_CAMPAIGN_SEND_ATTEMPT.json"


def _now(value: datetime | None) -> str:
    current = value if value is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("journal clock must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat(timespec="seconds")


def _safe(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID.fullmatch(text):
        raise ValueError(f"{name} contains unsupported characters")
    return text


def _stem(intent_id: str) -> str:
    return _safe(intent_id, "intent_id").replace(":", "_")


def _path(intent_id: str, directory: Path) -> Path:
    return directory / f"{_stem(intent_id)}.json"


def _attempt_path(intent_id: str, directory: Path) -> Path:
    return directory / f"{_stem(intent_id)}.attempted.json"


def _campaign_attempt_path(directory: Path) -> Path:
    return directory / CAMPAIGN_ATTEMPT_FILENAME


def _fsync_directory(directory: Path) -> None:
    """Fsync the directory itself so a new exclusive marker's dirent survives a crash.

    Fsyncing only the marker file guarantees the file's contents are durable,
    not that the directory entry pointing to it is. Without this, a power loss
    right after marker creation can lose the dirent and let a later restart
    create the marker again, spending a second irreversible send attempt.
    """
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_new(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)


def _atomic_replace(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _load_json(path: Path, *, label: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def load_send_journal(
    intent_id: str, *, directory: Path = DEFAULT_JOURNAL_DIR
) -> dict | None:
    path = _path(intent_id, directory)
    if not path.exists():
        return None
    return _load_json(path, label="send journal")


def send_attempt_recorded(
    intent_id: str, *, directory: Path = DEFAULT_JOURNAL_DIR
) -> bool:
    """Return True when the irreversible single-send marker already exists."""
    return _attempt_path(intent_id, directory).exists()


def campaign_send_attempt_recorded(*, directory: Path = DEFAULT_JOURNAL_DIR) -> bool:
    """Return True when the pilot-wide (not per-intent) send marker exists."""
    return _campaign_attempt_path(directory).exists()


def create_consumed_authorization_journal(
    *,
    intent_id: str,
    nonce: str,
    consumed_authorization: dict,
    directory: Path = DEFAULT_JOURNAL_DIR,
    now: datetime | None = None,
) -> dict:
    """Create a journal only from a proven consumed one-shot authorization."""
    intent = _safe(intent_id, "intent_id")
    safe_nonce = _safe(nonce, "nonce")
    if consumed_authorization.get("status") != "CONSUMED":
        raise PermissionError("one-shot authorization has not been consumed")
    if str(consumed_authorization.get("intent_id") or "") != intent:
        raise PermissionError("consumed authorization intent mismatch")
    if str(consumed_authorization.get("nonce") or "") != safe_nonce:
        raise PermissionError("consumed authorization nonce mismatch")
    if consumed_authorization.get("order_sent") or consumed_authorization.get(
        "live_order_sent"
    ):
        raise PermissionError("consumed authorization record is not pre-send evidence")
    if send_attempt_recorded(intent, directory=directory):
        raise PermissionError("a Live send attempt is already recorded for this intent")

    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "intent_id": intent,
        "nonce": safe_nonce,
        "state": "AUTHORIZATION_CONSUMED",
        "created_at": _now(now),
        "send_attempt_count": 0,
        "order_id": None,
        "perm_id": None,
        "recovery_required": False,
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
        "order_sent": False,
        "live_order_sent": False,
    }
    try:
        _atomic_new(_path(intent, directory), payload)
    except FileExistsError as exc:
        raise PermissionError("send journal already exists for this intent") from exc
    return payload


def record_send_attempt(
    intent_id: str,
    *,
    directory: Path = DEFAULT_JOURNAL_DIR,
    now: datetime | None = None,
) -> dict:
    """Irreversibly spend the sole allowed send attempt before broker transport.

    The exclusive attempt marker is created first.  If the process crashes or
    the summary update fails afterwards, that marker survives and every later
    call still fails closed.
    """
    intent = _safe(intent_id, "intent_id")
    payload = load_send_journal(intent, directory=directory)
    if payload is None:
        raise PermissionError("send journal is missing")
    if (
        payload.get("state") != "AUTHORIZATION_CONSUMED"
        or int(payload.get("send_attempt_count", 0)) != 0
    ):
        raise PermissionError("a Live send attempt is no longer permitted for this intent")

    # Create the pilot-wide (not per-intent) marker first. Its identity does
    # not vary with intent_id, so restarting under a brand-new intent_id/nonce
    # cannot bypass it and create a second reachable send attempt.
    campaign_marker = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "scope": "LIVE_PILOT_CAMPAIGN_SINGLE_SEND",
        "first_intent_id": intent,
        "recorded_at": _now(now),
        "automatic_resend_allowed": False,
    }
    try:
        _atomic_new(_campaign_attempt_path(directory), campaign_marker)
    except FileExistsError as exc:
        raise PermissionError(
            "the single Live send attempt for the entire pilot campaign has already been spent"
        ) from exc

    marker = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "intent_id": intent,
        "nonce": str(payload.get("nonce") or ""),
        "state": "SEND_ATTEMPT_RECORDED",
        "recorded_at": _now(now),
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
    }
    try:
        _atomic_new(_attempt_path(intent, directory), marker)
    except FileExistsError as exc:
        raise PermissionError("the single Live send attempt has already been spent") from exc

    payload.update(
        state="SEND_ATTEMPT_RECORDED",
        send_attempt_count=1,
        send_attempt_recorded_at=marker["recorded_at"],
        recovery_required=True,
        automatic_resend_allowed=False,
        automatic_cancel_allowed=False,
        automatic_modify_allowed=False,
        automatic_flatten_allowed=False,
        automatic_close_allowed=False,
    )
    _atomic_replace(_path(intent, directory), payload)
    return payload


def _require_attempt_marker(intent_id: str, directory: Path) -> None:
    if not send_attempt_recorded(intent_id, directory=directory):
        raise PermissionError("irreversible Live send-attempt marker is missing")


def load_send_attempt_marker(
    intent_id: str, *, directory: Path = DEFAULT_JOURNAL_DIR
) -> dict | None:
    """Load the immutable `.attempted.json` marker's own content, not just its presence.

    The completion judge must verify this marker itself (state/nonce/intent_id
    and every automatic-action flag), not merely trust the mutable summary
    journal's claimed state.
    """
    path = _attempt_path(intent_id, directory)
    if not path.exists():
        return None
    return _load_json(path, label="send-attempt marker")


def mark_order_acknowledged(
    intent_id: str,
    *,
    order_id: int,
    perm_id: int,
    directory: Path = DEFAULT_JOURNAL_DIR,
    now: datetime | None = None,
) -> dict:
    _require_attempt_marker(intent_id, directory)
    payload = load_send_journal(intent_id, directory=directory)
    if payload is None or payload.get("state") != "SEND_ATTEMPT_RECORDED":
        raise PermissionError("order acknowledgement is not valid in the current state")
    if int(order_id) <= 0 or int(perm_id) <= 0:
        raise ValueError("order_id and perm_id must be positive")
    payload.update(
        state="ORDER_ACKNOWLEDGED",
        order_id=int(order_id),
        perm_id=int(perm_id),
        acknowledged_at=_now(now),
        recovery_required=True,
    )
    _atomic_replace(_path(intent_id, directory), payload)
    return payload


def mark_unknown(
    intent_id: str,
    *,
    reason: str,
    directory: Path = DEFAULT_JOURNAL_DIR,
    now: datetime | None = None,
) -> dict:
    _require_attempt_marker(intent_id, directory)
    payload = load_send_journal(intent_id, directory=directory)
    if payload is None or int(payload.get("send_attempt_count", 0)) != 1:
        raise PermissionError("UNKNOWN is only valid after the single send attempt")
    if payload.get("state") in {"POSTFILL_PROVEN", "COMPLETE"}:
        raise PermissionError("completed evidence cannot be changed to UNKNOWN")
    normalized = str(reason or "").strip()
    if not normalized:
        raise ValueError("UNKNOWN reason is required")
    payload.update(
        state="UNKNOWN",
        unknown_at=_now(now),
        unknown_reason=normalized,
        recovery_required=True,
        automatic_resend_allowed=False,
        automatic_cancel_allowed=False,
        automatic_modify_allowed=False,
        automatic_flatten_allowed=False,
        automatic_close_allowed=False,
    )
    _atomic_replace(_path(intent_id, directory), payload)
    return payload


def mark_postfill_proven(
    intent_id: str,
    *,
    exec_id: str,
    order_id: int,
    perm_id: int,
    directory: Path = DEFAULT_JOURNAL_DIR,
    now: datetime | None = None,
) -> dict:
    _require_attempt_marker(intent_id, directory)
    payload = load_send_journal(intent_id, directory=directory)
    if payload is None or int(payload.get("send_attempt_count", 0)) != 1:
        raise PermissionError("post-fill proof requires the single recorded send attempt")
    if payload.get("state") not in {"ORDER_ACKNOWLEDGED", "UNKNOWN"}:
        raise PermissionError("post-fill proof is not valid in the current state")
    execution = _safe(exec_id, "exec_id")
    if int(order_id) <= 0 or int(perm_id) <= 0:
        raise ValueError("order_id and perm_id must be positive")
    existing_order = payload.get("order_id")
    existing_perm = payload.get("perm_id")
    if existing_order not in {None, int(order_id)} or existing_perm not in {
        None,
        int(perm_id),
    }:
        raise PermissionError("post-fill broker identity conflicts with acknowledged order")
    payload.update(
        state="POSTFILL_PROVEN",
        exec_id=execution,
        order_id=int(order_id),
        perm_id=int(perm_id),
        postfill_proven_at=_now(now),
        recovery_required=False,
        automatic_resend_allowed=False,
        automatic_cancel_allowed=False,
        automatic_modify_allowed=False,
        automatic_flatten_allowed=False,
        automatic_close_allowed=False,
    )
    _atomic_replace(_path(intent_id, directory), payload)
    return payload


def send_attempt_permitted(
    intent_id: str, *, directory: Path = DEFAULT_JOURNAL_DIR
) -> bool:
    """Fail closed if either the summary or irreversible marker says spent."""
    try:
        if send_attempt_recorded(intent_id, directory=directory):
            return False
        payload = load_send_journal(intent_id, directory=directory)
        return bool(
            payload
            and payload.get("state") == "AUTHORIZATION_CONSUMED"
            and int(payload.get("send_attempt_count", 0)) == 0
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
