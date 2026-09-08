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
_GLOBAL_ATTEMPT_FILENAME = "GLOBAL_SEND_ATTEMPT.lock"


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


def _global_attempt_path(directory: Path) -> Path:
    return directory / _GLOBAL_ATTEMPT_FILENAME


def _fsync_parent_dir(path: Path) -> None:
    """Fsync the containing directory so a new/removed entry survives a crash.

    A file's own fsync only guarantees its content is durable; the directory
    entry that makes the file (dis)appear needs a separate fsync on most
    POSIX filesystems, otherwise a power loss right after creation can boot
    back up without the entry and silently permit a second send attempt.
    """
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write_full(descriptor: int, data: bytes) -> None:
    """Write every byte of ``data``, since ``os.write`` may write fewer.

    POSIX permits a short write (e.g. an interrupted syscall); persisting
    without looping could fsync and publish a truncated marker/journal as if
    it were the complete, valid evidence it claims to be.
    """
    written = 0
    while written < len(data):
        count = os.write(descriptor, data[written:])
        if count <= 0:
            raise OSError("write() made no progress while persisting durable evidence")
        written += count


def _atomic_new(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _write_full(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_parent_dir(path)


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
        _write_full(descriptor, encoded)
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


def load_send_attempt_marker(
    intent_id: str, *, directory: Path = DEFAULT_JOURNAL_DIR
) -> dict | None:
    """Load the irreversible per-intent SEND_ATTEMPT marker, if it exists.

    This is the exclusive-create marker written by ``record_send_attempt``
    before any broker transport call, not the mutable summary journal. A
    completion judge must load and validate this marker directly rather than
    trusting the summary journal's ``state`` field alone.
    """
    path = _attempt_path(intent_id, directory)
    if not path.exists():
        return None
    return _load_json(path, label="send attempt marker")


def global_send_attempt_recorded(*, directory: Path = DEFAULT_JOURNAL_DIR) -> bool:
    """Return True when any Live pilot send attempt has ever been recorded.

    This marker has one fixed filename shared by every intent_id in the
    directory. It is what actually enforces "at most one transmission ever"
    for the whole pilot campaign: an intent-scoped marker alone would let a
    new or restarted caller choose a fresh intent_id and create a second,
    otherwise-unblocked attempt marker.
    """
    return _global_attempt_path(directory).exists()


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

    The exclusive global campaign marker is created first, before any
    per-intent marker. Its filename is fixed (not derived from intent_id), so
    switching to a new intent_id or restarting the process after a crash can
    never create a second reachable attempt. The per-intent attempt marker is
    then created for this intent's own bookkeeping. If the process crashes or
    the summary update fails afterwards, both markers survive and every later
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

    global_marker = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "intent_id": intent,
        "recorded_at": _now(now),
        "automatic_resend_allowed": False,
    }
    try:
        _atomic_new(_global_attempt_path(directory), global_marker)
    except FileExistsError as exc:
        raise PermissionError(
            "a Live send attempt has already been recorded for this pilot campaign"
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
    """Fail closed if the summary, per-intent marker, or global marker says spent."""
    try:
        if global_send_attempt_recorded(directory=directory):
            return False
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
