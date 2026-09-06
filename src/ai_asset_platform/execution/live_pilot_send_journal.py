"""Durable no-resend journal for one future Live pilot.

A future sender must persist SEND_ATTEMPT_RECORDED *before* calling any broker
order API. Once that state exists, this journal never permits another send
attempt for the same intent/nonce. Timeout, disconnect, exceptions, and any
ambiguous outcome transition to UNKNOWN and require read-only broker recovery.

This module has no broker connection or order API.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import os
import re


DEFAULT_JOURNAL_DIR = Path("results/live_pilot_send_journal")
REPORT_SCHEMA_VERSION = 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


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


def _path(intent_id: str, directory: Path) -> Path:
    safe = _safe(intent_id, "intent_id").replace(":", "_")
    return directory / f"{safe}.json"


def _atomic_new(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_replace(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_send_journal(intent_id: str, *, directory: Path = DEFAULT_JOURNAL_DIR) -> dict | None:
    path = _path(intent_id, directory)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(payload, dict):
        raise ValueError("send journal must be a JSON object")
    return payload


def create_consumed_authorization_journal(
    *, intent_id: str, nonce: str, consumed_authorization: dict,
    directory: Path = DEFAULT_JOURNAL_DIR, now: datetime | None = None,
) -> dict:
    """Create the journal only from a proven consumed one-shot authorization."""
    intent = _safe(intent_id, "intent_id")
    safe_nonce = _safe(nonce, "nonce")
    if consumed_authorization.get("status") != "CONSUMED":
        raise PermissionError("one-shot authorization has not been consumed")
    if str(consumed_authorization.get("intent_id") or "") != intent:
        raise PermissionError("consumed authorization intent mismatch")
    if str(consumed_authorization.get("nonce") or "") != safe_nonce:
        raise PermissionError("consumed authorization nonce mismatch")
    if consumed_authorization.get("order_sent") or consumed_authorization.get("live_order_sent"):
        raise PermissionError("consumed authorization record is not pre-send evidence")
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
        "order_sent": False,
        "live_order_sent": False,
    }
    try:
        _atomic_new(_path(intent, directory), payload)
    except FileExistsError as exc:
        raise PermissionError("send journal already exists for this intent") from exc
    return payload


def record_send_attempt(
    intent_id: str, *, directory: Path = DEFAULT_JOURNAL_DIR, now: datetime | None = None,
) -> dict:
    """Irreversibly record the sole allowed send attempt before broker transport."""
    payload = load_send_journal(intent_id, directory=directory)
    if payload is None:
        raise PermissionError("send journal is missing")
    if payload.get("state") != "AUTHORIZATION_CONSUMED" or int(payload.get("send_attempt_count", 0)) != 0:
        raise PermissionError("a Live send attempt is no longer permitted for this intent")
    payload.update(
        state="SEND_ATTEMPT_RECORDED",
        send_attempt_count=1,
        send_attempt_recorded_at=_now(now),
        recovery_required=True,
        automatic_resend_allowed=False,
    )
    _atomic_replace(_path(intent_id, directory), payload)
    return payload


def mark_order_acknowledged(
    intent_id: str, *, order_id: int, perm_id: int,
    directory: Path = DEFAULT_JOURNAL_DIR, now: datetime | None = None,
) -> dict:
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
    intent_id: str, *, reason: str,
    directory: Path = DEFAULT_JOURNAL_DIR, now: datetime | None = None,
) -> dict:
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
    )
    _atomic_replace(_path(intent_id, directory), payload)
    return payload


def mark_postfill_proven(
    intent_id: str, *, exec_id: str, order_id: int, perm_id: int,
    directory: Path = DEFAULT_JOURNAL_DIR, now: datetime | None = None,
) -> dict:
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
    if existing_order not in {None, int(order_id)} or existing_perm not in {None, int(perm_id)}:
        raise PermissionError("post-fill broker identity conflicts with acknowledged order")
    payload.update(
        state="POSTFILL_PROVEN",
        exec_id=execution,
        order_id=int(order_id),
        perm_id=int(perm_id),
        postfill_proven_at=_now(now),
        recovery_required=False,
        automatic_resend_allowed=False,
    )
    _atomic_replace(_path(intent_id, directory), payload)
    return payload


def send_attempt_permitted(intent_id: str, *, directory: Path = DEFAULT_JOURNAL_DIR) -> bool:
    payload = load_send_journal(intent_id, directory=directory)
    return bool(payload and payload.get("state") == "AUTHORIZATION_CONSUMED" and int(payload.get("send_attempt_count", 0)) == 0)
