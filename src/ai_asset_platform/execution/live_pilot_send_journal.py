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
import pwd
import re


DEFAULT_JOURNAL_DIR = Path("results/live_pilot_send_journal")
REPORT_SCHEMA_VERSION = 2
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_GLOBAL_ATTEMPT_FILENAME = "GLOBAL_SEND_ATTEMPT.lock"
_MACHINE_STATE_SUBDIR = (
    Path(".local") / "state" / "ai_asset_platform" / "live_pilot"
)


def _is_exact_int(value: object, expected: int) -> bool:
    """True only for the exact ``int`` value, not ``0.0``, ``"0"``, or ``False``.

    ``int(value)`` silently coerces all of those (and ``bool`` is itself an
    ``int`` subclass), which would let a malformed persisted
    ``send_attempt_count`` pass a state-transition gate.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


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


def _terminal_path(intent_id: str, directory: Path) -> Path:
    return directory / f"{_stem(intent_id)}.terminal.json"


def _resolve_machine_state_root() -> Path:
    """Resolve checkout-independent durable operator state for the campaign marker."""
    try:
        effective_uid = os.geteuid()
        passwd_home = pwd.getpwuid(effective_uid).pw_dir
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        raise OSError("durable operator identity cannot be resolved") from exc
    if not isinstance(passwd_home, str) or not passwd_home.strip():
        raise OSError("durable operator home must be non-empty")
    try:
        home = Path(passwd_home)
    except (OSError, TypeError, ValueError) as exc:
        raise OSError("durable operator home is invalid") from exc
    if not home.is_absolute():
        raise OSError("durable operator home must be an absolute path")
    return home / _MACHINE_STATE_SUBDIR


def _canonical_journal_root() -> Path:
    """Return the one true machine/operator-state location for the campaign marker."""
    return _resolve_machine_state_root()


def _global_attempt_path(directory: Path) -> Path:
    # Deliberately ignores caller storage, cwd, checkout path, and intent_id.
    del directory
    root = _canonical_journal_root()
    _mkdir_durable(root)
    return root / _GLOBAL_ATTEMPT_FILENAME


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


def _mkdir_durable(directory: Path) -> None:
    """Create ``directory`` and any missing parents, durably.

    ``Path.mkdir(parents=True)`` alone does not guarantee the new directory
    entries survive a crash immediately after this call returns; each newly
    created directory's own parent must be fsynced too. Without this, a
    power loss right after the very first pilot run creates
    ``results/live_pilot_send_journal/`` could lose the entire new
    directory, including a marker written into it moments later.
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
    _mkdir_durable(path.parent)
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
    _mkdir_durable(path.parent)
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
    _fsync_parent_dir(path)


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


def load_terminal_reconciliation_marker(
    intent_id: str, *, directory: Path = DEFAULT_JOURNAL_DIR
) -> dict | None:
    """Load the exclusive terminal-reconciliation proof, if it exists.

    This record is created exactly once before the mutable summary journal is
    advanced to PARTIAL_RECONCILED or REJECTED_RECONCILED.  Recovery treats
    this marker, not the mutable summary, as the durable state-specific proof.
    """
    path = _terminal_path(intent_id, directory)
    if not path.exists():
        return None
    return _load_json(path, label="terminal reconciliation marker")


def load_global_send_attempt_marker(
    *, directory: Path = DEFAULT_JOURNAL_DIR
) -> dict | None:
    """Load the campaign-wide GLOBAL_SEND_ATTEMPT marker, if it exists.

    A completion judge must validate this in addition to the per-intent
    marker: an intent's own ``.attempted.json`` can exist and look valid
    even if the global marker was lost or now belongs to a different
    intent, which would otherwise let completion be reported for one intent
    without proving the campaign-wide one-send guarantee actually held.
    """
    path = _global_attempt_path(directory)
    if not path.exists():
        return None
    return _load_json(path, label="global send attempt marker")


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

    ticker = str(consumed_authorization.get("ticker") or "").strip().upper()
    side = str(consumed_authorization.get("side") or "").strip().upper()
    quantity = consumed_authorization.get("quantity")
    limit_price = consumed_authorization.get("limit_price")
    estimated_notional_jpy = consumed_authorization.get("estimated_notional_jpy")
    account_fingerprint = str(
        consumed_authorization.get("account_fingerprint") or ""
    ).strip().lower()
    endpoint_port = consumed_authorization.get("endpoint_port")
    if not ticker:
        raise PermissionError("consumed authorization ticker binding is missing")
    if side not in {"BUY", "SELL"}:
        raise PermissionError("consumed authorization side binding is invalid")
    if (
        not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity <= 0
    ):
        raise PermissionError("consumed authorization quantity binding is invalid")
    for name, value in (
        ("limit_price", limit_price),
        ("estimated_notional_jpy", estimated_notional_jpy),
    ):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value <= 0
            or value != value
            or value in {float("inf"), float("-inf")}
        ):
            raise PermissionError(f"consumed authorization {name} binding is invalid")
    if (
        len(account_fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in account_fingerprint)
    ):
        raise PermissionError("consumed authorization account binding is invalid")
    if (
        not isinstance(endpoint_port, int)
        or isinstance(endpoint_port, bool)
        or endpoint_port not in {4001, 7496}
    ):
        raise PermissionError("consumed authorization endpoint binding is invalid")

    if send_attempt_recorded(intent, directory=directory):
        raise PermissionError("a Live send attempt is already recorded for this intent")

    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "intent_id": intent,
        "nonce": safe_nonce,
        "state": "AUTHORIZATION_CONSUMED",
        "created_at": _now(now),
        "authorized_ticker": ticker,
        "authorized_side": side,
        "authorized_quantity": quantity,
        "authorized_limit_price": float(limit_price),
        "authorized_estimated_notional_jpy": float(estimated_notional_jpy),
        "authorized_account_fingerprint": account_fingerprint,
        "authorized_endpoint_port": endpoint_port,
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
        or not _is_exact_int(payload.get("send_attempt_count"), 0)
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



def record_order_id_before_transport(
    intent_id: str,
    *,
    order_id: int,
    client_id: int,
    directory: Path = DEFAULT_JOURNAL_DIR,
    now: datetime | None = None,
) -> dict:
    """Durably bind the locally assigned broker order id before transport.

    The order id is available after nextValidId and before placeOrder. Persisting
    it while the irreversible send-attempt marker already exists gives later
    read-only UNKNOWN recovery a stable broker key even if acknowledgement (and
    therefore permId) never arrives. This does not authorize, transmit, retry,
    cancel, modify, flatten, or close an order.
    """
    _require_attempt_marker(intent_id, directory)
    payload = load_send_journal(intent_id, directory=directory)
    if payload is None or payload.get("state") != "SEND_ATTEMPT_RECORDED":
        raise PermissionError(
            "pre-transport broker identity is only valid after the send attempt is recorded"
        )
    if not isinstance(order_id, int) or isinstance(order_id, bool) or order_id <= 0:
        raise ValueError("order_id must be a positive exact int")
    if not isinstance(client_id, int) or isinstance(client_id, bool) or client_id < 0:
        raise ValueError("client_id must be a non-negative exact int")
    existing = payload.get("order_id")
    if existing not in {None, order_id}:
        raise PermissionError("pre-transport broker order_id conflicts with persisted identity")
    existing_client = payload.get("sender_client_id")
    if existing_client not in {None, client_id}:
        raise PermissionError("pre-transport broker client_id conflicts with persisted identity")
    payload.update(
        order_id=order_id,
        sender_client_id=client_id,
        order_id_recorded_at=_now(now),
        recovery_required=True,
        automatic_resend_allowed=False,
        automatic_cancel_allowed=False,
        automatic_modify_allowed=False,
        automatic_flatten_allowed=False,
        automatic_close_allowed=False,
    )
    _atomic_replace(_path(intent_id, directory), payload)
    return payload

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
    if (
        not isinstance(order_id, int)
        or isinstance(order_id, bool)
        or order_id <= 0
        or not isinstance(perm_id, int)
        or isinstance(perm_id, bool)
        or perm_id <= 0
    ):
        raise ValueError("order_id and perm_id must be positive exact ints")
    payload.update(
        state="ORDER_ACKNOWLEDGED",
        order_id=order_id,
        perm_id=perm_id,
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
    if payload is None or not _is_exact_int(payload.get("send_attempt_count"), 1):
        raise PermissionError("UNKNOWN is only valid after the single send attempt")
    if payload.get("state") in {
        "POSTFILL_PROVEN",
        "COMPLETE",
        "PARTIAL_RECONCILED",
        "REJECTED_RECONCILED",
    }:
        raise PermissionError("reconciled evidence cannot be changed to UNKNOWN")
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


def _validated_attempt_marker_timestamp(
    payload: dict,
    *,
    intent_id: str,
    directory: Path,
) -> str:
    """Validate both irreversible attempt markers before a terminal transition."""
    try:
        attempt = load_send_attempt_marker(intent_id, directory=directory)
        global_attempt = load_global_send_attempt_marker(directory=directory)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise PermissionError("irreversible attempt marker evidence is unreadable") from exc
    if not isinstance(attempt, dict) or not isinstance(global_attempt, dict):
        raise PermissionError("both irreversible attempt markers are required")
    if (
        attempt.get("schema_version") != REPORT_SCHEMA_VERSION
        or global_attempt.get("schema_version") != REPORT_SCHEMA_VERSION
        or attempt.get("state") != "SEND_ATTEMPT_RECORDED"
        or str(attempt.get("intent_id") or "") != intent_id
        or str(global_attempt.get("intent_id") or "") != intent_id
        or str(attempt.get("nonce") or "") != str(payload.get("nonce") or "")
        or attempt.get("automatic_resend_allowed") is not False
        or global_attempt.get("automatic_resend_allowed") is not False
    ):
        raise PermissionError("irreversible attempt marker binding is invalid")
    for flag in (
        "automatic_cancel_allowed",
        "automatic_modify_allowed",
        "automatic_flatten_allowed",
        "automatic_close_allowed",
    ):
        if attempt.get(flag) is not False:
            raise PermissionError("irreversible attempt marker action flags are invalid")

    recorded_at = str(attempt.get("recorded_at") or "").strip()
    global_recorded_at = str(global_attempt.get("recorded_at") or "").strip()
    journal_recorded_at = str(payload.get("send_attempt_recorded_at") or "").strip()
    try:
        attempt_time = datetime.fromisoformat(recorded_at)
        global_time = datetime.fromisoformat(global_recorded_at)
        journal_time = datetime.fromisoformat(journal_recorded_at)
    except ValueError as exc:
        raise PermissionError("irreversible attempt marker timestamp is invalid") from exc
    for observed in (attempt_time, global_time, journal_time):
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise PermissionError("irreversible attempt marker timestamp is not timezone-aware")
    attempt_time = attempt_time.astimezone(timezone.utc)
    global_time = global_time.astimezone(timezone.utc)
    journal_time = journal_time.astimezone(timezone.utc)
    if global_time > attempt_time or journal_time != attempt_time:
        raise PermissionError("irreversible attempt marker timestamps conflict")
    return attempt_time.isoformat(timespec="seconds")


def _terminal_marker_base(
    payload: dict,
    *,
    intent_id: str,
    state: str,
    order_id: int,
    recorded_at: str,
    reconciled_at: str,
) -> dict:
    sender_client_id = payload.get("sender_client_id")
    ticker = str(payload.get("authorized_ticker") or "").strip().upper()
    side = str(payload.get("authorized_side") or "").strip().upper()
    quantity = payload.get("authorized_quantity")
    limit_price = payload.get("authorized_limit_price")
    notional = payload.get("authorized_estimated_notional_jpy")
    fingerprint = str(
        payload.get("authorized_account_fingerprint") or ""
    ).strip().lower()
    endpoint_port = payload.get("authorized_endpoint_port")
    if (
        not isinstance(sender_client_id, int)
        or isinstance(sender_client_id, bool)
        or sender_client_id < 0
    ):
        raise PermissionError("terminal reconciliation sender client_id is invalid")
    if not ticker or side not in {"BUY", "SELL"}:
        raise PermissionError("terminal reconciliation authorization binding is invalid")
    if (
        not isinstance(quantity, int)
        or isinstance(quantity, bool)
        or quantity <= 0
    ):
        raise PermissionError("terminal reconciliation quantity binding is invalid")
    for name, value in (("limit_price", limit_price), ("notional", notional)):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value <= 0
            or value != value
            or value in {float("inf"), float("-inf")}
        ):
            raise PermissionError(
                f"terminal reconciliation {name} binding is invalid"
            )
    if (
        len(fingerprint) != 64
        or any(ch not in "0123456789abcdef" for ch in fingerprint)
    ):
        raise PermissionError("terminal reconciliation account binding is invalid")
    if (
        not isinstance(endpoint_port, int)
        or isinstance(endpoint_port, bool)
        or endpoint_port not in {4001, 7496}
    ):
        raise PermissionError("terminal reconciliation endpoint binding is invalid")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "intent_id": intent_id,
        "nonce": str(payload.get("nonce") or ""),
        "state": state,
        "authorized_ticker": ticker,
        "authorized_side": side,
        "authorized_quantity": quantity,
        "authorized_limit_price": float(limit_price),
        "authorized_estimated_notional_jpy": float(notional),
        "authorized_account_fingerprint": fingerprint,
        "authorized_endpoint_port": endpoint_port,
        "send_attempt_count": 1,
        "send_attempt_recorded_at": recorded_at,
        "terminal_recorded_at": reconciled_at,
        "order_id": order_id,
        "sender_client_id": sender_client_id,
        "recovery_required": False,
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
        "order_sent": False,
        "live_order_sent": False,
    }


def mark_partial_reconciled(
    intent_id: str,
    *,
    exec_ids: tuple[str, ...],
    order_id: int,
    perm_id: int,
    filled_quantity: float,
    commission_total: float,
    commission_currency: str,
    final_position_quantity: float,
    directory: Path = DEFAULT_JOURNAL_DIR,
    now: datetime | None = None,
) -> dict:
    """Persist a terminal, read-only reconciled partial-fill outcome.

    This never authorizes or sends the unfilled remainder.
    """
    _require_attempt_marker(intent_id, directory)
    payload = load_send_journal(intent_id, directory=directory)
    if payload is None or not _is_exact_int(payload.get("send_attempt_count"), 1):
        raise PermissionError("partial reconciliation requires the recorded send attempt")
    if payload.get("state") not in {
        "SEND_ATTEMPT_RECORDED",
        "ORDER_ACKNOWLEDGED",
        "UNKNOWN",
    }:
        raise PermissionError("partial reconciliation is not valid in the current state")
    if not isinstance(order_id, int) or isinstance(order_id, bool) or order_id <= 0:
        raise ValueError("order_id must be a positive exact int")
    if not isinstance(perm_id, int) or isinstance(perm_id, bool) or perm_id <= 0:
        raise ValueError("perm_id must be a positive exact int")
    normalized_exec_ids = tuple(_safe(value, "exec_id") for value in exec_ids)
    if not normalized_exec_ids or len(normalized_exec_ids) != len(set(normalized_exec_ids)):
        raise ValueError("partial reconciliation requires unique execution ids")
    for name, value in (
        ("filled_quantity", filled_quantity),
        ("commission_total", commission_total),
        ("final_position_quantity", final_position_quantity),
    ):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be numeric")
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{name} must be finite")
    if float(filled_quantity) <= 0:
        raise ValueError("filled_quantity must be positive")
    currency = str(commission_currency or "").strip().upper()
    if len(currency) != 3:
        raise ValueError("commission_currency must be a three-letter code")
    existing_order = payload.get("order_id")
    existing_perm = payload.get("perm_id")
    if existing_order not in {None, order_id}:
        raise PermissionError("partial reconciliation order_id conflicts with journal")
    if existing_perm not in {None, perm_id}:
        raise PermissionError("partial reconciliation perm_id conflicts with journal")

    attempt_recorded_at = _validated_attempt_marker_timestamp(
        payload,
        intent_id=intent_id,
        directory=directory,
    )
    reconciled_at = _now(now)
    terminal_marker = _terminal_marker_base(
        payload,
        intent_id=intent_id,
        state="PARTIAL_RECONCILED",
        order_id=order_id,
        recorded_at=attempt_recorded_at,
        reconciled_at=reconciled_at,
    )
    terminal_marker.update(
        perm_id=perm_id,
        exec_ids=list(normalized_exec_ids),
        filled_quantity=float(filled_quantity),
        commission_total=float(commission_total),
        commission_currency=currency,
        final_position_quantity=float(final_position_quantity),
    )
    try:
        _atomic_new(_terminal_path(intent_id, directory), terminal_marker)
    except FileExistsError as exc:
        raise PermissionError(
            "terminal reconciliation marker already exists for this intent"
        ) from exc

    payload.update(
        state="PARTIAL_RECONCILED",
        order_id=order_id,
        perm_id=perm_id,
        exec_ids=list(normalized_exec_ids),
        filled_quantity=float(filled_quantity),
        commission_total=float(commission_total),
        commission_currency=currency,
        final_position_quantity=float(final_position_quantity),
        reconciled_at=reconciled_at,
        recovery_required=False,
        automatic_resend_allowed=False,
        automatic_cancel_allowed=False,
        automatic_modify_allowed=False,
        automatic_flatten_allowed=False,
        automatic_close_allowed=False,
    )
    _atomic_replace(_path(intent_id, directory), payload)
    return payload


def _definitive_terminal_rejection_reason(value: object) -> str | None:
    reason = str(value or "").strip()
    for prefix in (
        "broker orderStatus callback reported non-accepted status:",
        "broker openOrder callback reported non-accepted status:",
    ):
        if reason.startswith(prefix):
            status = reason[len(prefix) :].strip()
            return reason if status in {"Cancelled", "ApiCancelled"} else None
    parts = reason.split(":", 2)
    if (
        len(parts) == 3
        and parts[0].isdigit()
        and parts[1].isdigit()
        and int(parts[1]) in {201, 202}
    ):
        return reason
    return None


def mark_rejected_reconciled(
    intent_id: str,
    *,
    rejection_reason: str,
    order_id: int,
    final_position_quantity: float,
    directory: Path = DEFAULT_JOURNAL_DIR,
    now: datetime | None = None,
) -> dict:
    """Persist a terminal rejected/no-fill outcome proven by read-only evidence."""
    _require_attempt_marker(intent_id, directory)
    payload = load_send_journal(intent_id, directory=directory)
    if payload is None or not _is_exact_int(payload.get("send_attempt_count"), 1):
        raise PermissionError("rejection reconciliation requires the recorded send attempt")
    if payload.get("state") not in {
        "SEND_ATTEMPT_RECORDED",
        "ORDER_ACKNOWLEDGED",
        "UNKNOWN",
    }:
        raise PermissionError("rejection reconciliation is not valid in the current state")
    if not isinstance(order_id, int) or isinstance(order_id, bool) or order_id <= 0:
        raise ValueError("order_id must be a positive exact int")
    reason = _definitive_terminal_rejection_reason(rejection_reason)
    if reason is None:
        raise ValueError("rejection_reason must prove a terminal broker rejection")
    if not isinstance(final_position_quantity, (int, float)) or isinstance(
        final_position_quantity, bool
    ):
        raise ValueError("final_position_quantity must be numeric")
    if final_position_quantity != final_position_quantity or final_position_quantity in {
        float("inf"),
        float("-inf"),
    }:
        raise ValueError("final_position_quantity must be finite")
    existing_order = payload.get("order_id")
    if existing_order not in {None, order_id}:
        raise PermissionError("rejection reconciliation order_id conflicts with journal")

    attempt_recorded_at = _validated_attempt_marker_timestamp(
        payload,
        intent_id=intent_id,
        directory=directory,
    )
    reconciled_at = _now(now)
    terminal_marker = _terminal_marker_base(
        payload,
        intent_id=intent_id,
        state="REJECTED_RECONCILED",
        order_id=order_id,
        recorded_at=attempt_recorded_at,
        reconciled_at=reconciled_at,
    )
    terminal_marker.update(
        perm_id=None,
        rejection_reason=reason,
        final_position_quantity=float(final_position_quantity),
    )
    try:
        _atomic_new(_terminal_path(intent_id, directory), terminal_marker)
    except FileExistsError as exc:
        raise PermissionError(
            "terminal reconciliation marker already exists for this intent"
        ) from exc

    payload.update(
        state="REJECTED_RECONCILED",
        order_id=order_id,
        rejection_reason=reason,
        final_position_quantity=float(final_position_quantity),
        reconciled_at=reconciled_at,
        recovery_required=False,
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
    if payload is None or not _is_exact_int(payload.get("send_attempt_count"), 1):
        raise PermissionError("post-fill proof requires the single recorded send attempt")
    if payload.get("state") not in {
        "SEND_ATTEMPT_RECORDED",
        "ORDER_ACKNOWLEDGED",
        "UNKNOWN",
    }:
        raise PermissionError("post-fill proof is not valid in the current state")
    execution = _safe(exec_id, "exec_id")
    if (
        not isinstance(order_id, int)
        or isinstance(order_id, bool)
        or order_id <= 0
        or not isinstance(perm_id, int)
        or isinstance(perm_id, bool)
        or perm_id <= 0
    ):
        raise ValueError("order_id and perm_id must be positive exact ints")
    existing_order = payload.get("order_id")
    existing_perm = payload.get("perm_id")
    if existing_order not in {None, order_id} or existing_perm not in {
        None,
        perm_id,
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
            and _is_exact_int(payload.get("send_attempt_count"), 0)
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
