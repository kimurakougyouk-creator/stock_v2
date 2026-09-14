"""Durable, single-use operator authorization for one bounded Live pilot.

This module does not connect to a broker and cannot place, cancel, modify, retry,
flatten, or close an order.  It only binds an explicit operator approval to one
exact pilot intent and provides an atomic, fail-closed consumption primitive for
a future Live sender.

The raw IBKR account identifier is never accepted or persisted; callers bind the
authorization to the already-pinned SHA-256 account fingerprint instead.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import secrets


OPERATOR_CONFIRMATION_VALUE = "AUTHORIZE_ONE_LIVE_PILOT_ONLY"
DEFAULT_AUTHORIZATION_DIR = Path("results/live_pilot_authorizations")
DEFAULT_TTL_SECONDS = 120.0
MAX_TTL_SECONDS = 300.0
REPORT_SCHEMA_VERSION = 1
_VALID_LIVE_ENDPOINT_PORTS = {4001, 7496}


@dataclass(frozen=True)
class LivePilotAuthorization:
    nonce: str
    intent_id: str
    ticker: str
    side: str
    quantity: int
    limit_price: float
    estimated_notional_jpy: float
    account_fingerprint: str
    endpoint_port: int
    created_at: str
    expires_at: str
    status: str = "AUTHORIZED_ONCE"
    raw_account_id_persisted: bool = False
    broker_connection_used: bool = False
    order_sent: bool = False
    live_order_sent: bool = False


def _aware_utc(value: datetime | None) -> datetime:
    current = value if value is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("authorization clock must be timezone-aware")
    return current.astimezone(timezone.utc)


def _positive_finite(value: object, *, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive finite number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return parsed


def _normalized_text(value: object, *, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _authorization_path(directory: Path, nonce: str) -> Path:
    safe_nonce = _normalized_text(nonce, name="nonce")
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in safe_nonce):
        raise ValueError("nonce contains unsupported characters")
    return directory / f"{safe_nonce}.json"


def _consumed_path(directory: Path, nonce: str) -> Path:
    return _authorization_path(directory, nonce).with_suffix(".consumed.json")


def _fsync_parent_dir(path: Path) -> None:
    """Fsync the containing directory so a new/removed entry survives a crash.

    A file's own fsync only guarantees its content is durable; the directory
    entry that makes the file (dis)appear needs a separate fsync on most
    POSIX filesystems, otherwise a power loss right after this call can boot
    back up without the entry and silently permit consuming the same
    authorization (or reusing an authorization file) a second time.
    """
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _mkdir_durable(directory: Path) -> None:
    """Create ``directory`` and any missing parents, durably.

    ``Path.mkdir(parents=True)`` alone does not guarantee the new directory
    entries survive a crash immediately after this call returns; each newly
    created directory's own parent must be fsynced too, or a power loss
    right after the first authorization is issued could lose the entire new
    ``results/live_pilot_authorizations/`` directory.
    """
    to_create: list[Path] = []
    probe = directory
    while not probe.exists():
        to_create.append(probe)
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    directory.mkdir(parents=True, exist_ok=True)
    for created in reversed(to_create):
        _fsync_parent_dir(created)


def _write_full(descriptor: int, data: bytes) -> None:
    """Write every byte of ``data``, since ``os.write`` may write fewer.

    POSIX permits a short write (e.g. an interrupted syscall); persisting
    without looping could fsync and publish a truncated authorization/
    consumed-marker record as if it were the complete, valid evidence it
    claims to be.
    """
    written = 0
    while written < len(data):
        count = os.write(descriptor, data[written:])
        if count <= 0:
            raise OSError("write() made no progress while persisting durable evidence")
        written += count


def _exclusive_write_json(path: Path, payload: dict) -> None:
    _mkdir_durable(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        _write_full(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_parent_dir(path)


def issue_live_pilot_authorization(
    *,
    confirmation: str,
    intent_id: str,
    ticker: str,
    side: str,
    quantity: int,
    limit_price: float,
    estimated_notional_jpy: float,
    account_fingerprint: str,
    endpoint_port: int,
    authorization_dir: Path = DEFAULT_AUTHORIZATION_DIR,
    now: datetime | None = None,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> LivePilotAuthorization:
    """Persist one short-lived authorization bound to an exact Live pilot intent."""
    if str(confirmation or "").strip() != OPERATOR_CONFIRMATION_VALUE:
        raise PermissionError("exact one-pilot operator confirmation is missing")

    current = _aware_utc(now)
    ttl = _positive_finite(ttl_seconds, name="ttl_seconds")
    if ttl > MAX_TTL_SECONDS:
        raise ValueError("ttl_seconds exceeds the maximum one-shot authorization window")

    normalized_intent = _normalized_text(intent_id, name="intent_id")
    normalized_ticker = _normalized_text(ticker, name="ticker").upper()
    normalized_side = _normalized_text(side, name="side").upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    try:
        normalized_quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("quantity must be a positive integer") from exc
    if normalized_quantity <= 0 or normalized_quantity != quantity:
        raise ValueError("quantity must be a positive integer")

    parsed_limit = _positive_finite(limit_price, name="limit_price")
    parsed_notional = _positive_finite(
        estimated_notional_jpy, name="estimated_notional_jpy"
    )
    fingerprint = _normalized_text(account_fingerprint, name="account_fingerprint")
    if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint.lower()):
        raise ValueError("account_fingerprint must be a SHA-256 hex digest")
    try:
        port = int(endpoint_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("endpoint_port must identify an audited Live endpoint") from exc
    if port not in _VALID_LIVE_ENDPOINT_PORTS:
        raise ValueError("endpoint_port must identify an audited Live endpoint")

    nonce = secrets.token_urlsafe(32)
    expires = current + timedelta(seconds=ttl)
    authorization = LivePilotAuthorization(
        nonce=nonce,
        intent_id=normalized_intent,
        ticker=normalized_ticker,
        side=normalized_side,
        quantity=normalized_quantity,
        limit_price=parsed_limit,
        estimated_notional_jpy=parsed_notional,
        account_fingerprint=fingerprint.lower(),
        endpoint_port=port,
        created_at=current.isoformat(timespec="seconds"),
        expires_at=expires.isoformat(timespec="seconds"),
    )
    payload = {"schema_version": REPORT_SCHEMA_VERSION, **asdict(authorization)}
    _exclusive_write_json(_authorization_path(authorization_dir, nonce), payload)
    return authorization


def _load_authorization(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(payload, dict):
        raise ValueError("authorization record must be a JSON object")
    return payload


def consume_live_pilot_authorization(
    *,
    nonce: str,
    intent_id: str,
    ticker: str,
    side: str,
    quantity: int,
    limit_price: float,
    estimated_notional_jpy: float,
    account_fingerprint: str,
    endpoint_port: int,
    authorization_dir: Path = DEFAULT_AUTHORIZATION_DIR,
    now: datetime | None = None,
) -> dict:
    """Atomically consume exactly one matching authorization.

    The exclusive consumed marker is created before the function reports
    success. A crash after marker creation therefore fails closed on replay.
    """
    current = _aware_utc(now)
    auth_path = _authorization_path(authorization_dir, nonce)
    consumed_path = _consumed_path(authorization_dir, nonce)
    if consumed_path.exists():
        raise PermissionError("authorization nonce has already been consumed")
    if not auth_path.exists():
        raise PermissionError("authorization nonce is missing")

    payload = _load_authorization(auth_path)
    try:
        expires = datetime.fromisoformat(str(payload.get("expires_at") or ""))
    except ValueError as exc:
        raise PermissionError("authorization expiry is invalid") from exc
    if expires.tzinfo is None or expires.utcoffset() is None:
        raise PermissionError("authorization expiry is not timezone-aware")
    if current > expires.astimezone(timezone.utc):
        raise PermissionError("authorization nonce has expired")

    expected = {
        "status": "AUTHORIZED_ONCE",
        "nonce": str(nonce),
        "intent_id": _normalized_text(intent_id, name="intent_id"),
        "ticker": _normalized_text(ticker, name="ticker").upper(),
        "side": _normalized_text(side, name="side").upper(),
        "quantity": int(quantity),
        "limit_price": _positive_finite(limit_price, name="limit_price"),
        "estimated_notional_jpy": _positive_finite(
            estimated_notional_jpy, name="estimated_notional_jpy"
        ),
        "account_fingerprint": _normalized_text(
            account_fingerprint, name="account_fingerprint"
        ).lower(),
        "endpoint_port": int(endpoint_port),
        "raw_account_id_persisted": False,
        "broker_connection_used": False,
        "order_sent": False,
        "live_order_sent": False,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise PermissionError(f"authorization binding mismatch: {key}")

    consumed_record = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "CONSUMED",
        "nonce": str(nonce),
        "intent_id": expected["intent_id"],
        "consumed_at": current.isoformat(timespec="seconds"),
        # Preserved so a caller can re-validate expiry after this call, e.g.
        # if durable writes between consumption and transport stall long
        # enough for the original TTL to elapse even though this check
        # already passed.
        "expires_at": payload.get("expires_at"),
        "order_sent": False,
        "live_order_sent": False,
    }
    try:
        _exclusive_write_json(consumed_path, consumed_record)
    except FileExistsError as exc:
        raise PermissionError("authorization nonce has already been consumed") from exc

    try:
        auth_path.unlink()
    except FileNotFoundError:
        # Another actor changing the authorization after the exclusive marker is
        # an unknown state; preserve the consumed marker and fail closed.
        raise PermissionError("authorization state changed during consumption")
    _fsync_parent_dir(auth_path)
    return consumed_record


def authorization_consumed(
    nonce: str, *, authorization_dir: Path = DEFAULT_AUTHORIZATION_DIR
) -> bool:
    return _consumed_path(authorization_dir, nonce).exists()
