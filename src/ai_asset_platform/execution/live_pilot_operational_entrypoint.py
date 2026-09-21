"""Single operational entrypoint for the bounded first IBKR Live pilot.

This module wires the already-audited Issue #255 components into one fail-closed
state machine:

1. collect fresh read-only Live evidence;
2. evaluate operational readiness and same-run preflight;
3. call the existing exactly-once sender only when every gate is ready;
4. after any irreversible send attempt, switch permanently to read-only
   reconciliation;
5. collect one fresh post-fill/account/open-order snapshot and evaluate the
   existing completion judge.

The coordinator never retries a Live send.  If the campaign-wide send-attempt
marker already exists, the sender is unreachable and only read-only recovery is
performed.  It never cancels, modifies, resends, flattens, or closes an order,
and it never changes broker API Read-Only settings.

No broker action occurs merely by importing this module.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path

from ai_asset_platform.brokers.ibkr_live_all_open_orders import (
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_OPEN_ORDERS_REPORT,
    REPORT_SCHEMA_VERSION as LIVE_OPEN_ORDERS_SCHEMA_VERSION,
    persist_live_all_open_orders,
    preview_ibkr_live_all_open_orders,
)
from ai_asset_platform.brokers.ibkr_live_completed_orders import (
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_COMPLETED_ORDERS_REPORT,
    REPORT_SCHEMA_VERSION as LIVE_COMPLETED_ORDERS_SCHEMA_VERSION,
    persist_live_completed_orders,
    preview_ibkr_live_completed_orders,
)
from ai_asset_platform.brokers.ibkr_live_fx_evidence import (
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_FX_REPORT,
    persist_live_fx_evidence,
    resolve_ibkr_live_fx_evidence,
)
from ai_asset_platform.brokers.ibkr_live_postfill_evidence import (
    DEFAULT_REPORT_PATH as DEFAULT_POSTFILL_REPORT,
    REPORT_SCHEMA_VERSION as LIVE_POSTFILL_SCHEMA_VERSION,
    match_live_postfill,
    persist_live_postfill_snapshot,
    preview_ibkr_live_postfill_snapshot,
)
from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    CONFIRMATION_VALUE as LIVE_READONLY_CONFIRMATION_VALUE,
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_ACCOUNT_REPORT,
    REPORT_SCHEMA_VERSION as LIVE_ACCOUNT_SCHEMA_VERSION,
    persist_live_readonly_account_snapshot,
    preview_ibkr_live_readonly_account_snapshot,
)
from ai_asset_platform.execution.live_pilot_completion import (
    DEFAULT_COMPLETION_REPORT,
    DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
    DEFAULT_OPERATOR_ALERT,
    _clean_live_report,
    _fresh,
    _paper_safe,
    _parse_aware_timestamp,
    _target_position_quantity,
    audit_live_pilot_completion,
    persist_live_pilot_completion,
)
from ai_asset_platform.execution.live_pilot_same_run_preflight import (
    LivePilotSameRunPreflight,
    evaluate_live_pilot_same_run_preflight,
    preflight_record,
)
from ai_asset_platform.execution.live_pilot_one_shot_authorization import (
    load_live_pilot_authorization_binding,
)
from ai_asset_platform.execution.live_pilot_send_journal import (
    DEFAULT_JOURNAL_DIR,
    REPORT_SCHEMA_VERSION as SEND_JOURNAL_SCHEMA_VERSION,
    global_send_attempt_recorded,
    load_definitive_rejection_evidence,
    load_global_send_attempt_marker,
    load_send_attempt_marker,
    load_send_journal,
    load_terminal_reconciliation_marker,
    mark_partial_reconciled,
    mark_postfill_proven,
    mark_rejected_reconciled,
    record_definitive_rejection_evidence,
)
from ai_asset_platform.execution.live_pilot_single_send import (
    LivePilotSendRequest,
    LivePilotSendResult,
    send_exactly_one_live_pilot,
)
from ai_asset_platform.execution.live_pilot_source_cutover import (
    audit_live_pilot_source_cutover,
)
from ai_asset_platform.reports.live_operational_pilot_readiness import (
    DEFAULT_PAPER_MONITOR_REPORT,
    DEFAULT_REPORT_PATH as DEFAULT_READINESS_REPORT,
    audit_live_operational_pilot_readiness,
    persist_live_operational_pilot_readiness,
    readiness_record,
)


DEFAULT_PREFLIGHT_REPORT = Path("results/live_pilot_same_run_preflight_latest.json")
DEFAULT_OPERATIONAL_RESULT = Path("results/live_pilot_operational_once_latest.json")
_USD_TICKERS = {"AAPL", "SPY"}
_DEFINITIVE_REJECTION_STATUSES = {"Cancelled", "ApiCancelled"}
_DEFINITIVE_REJECTION_ERROR_CODES = {201, 202}


@dataclass(frozen=True)
class LivePilotOperationalRequest:
    intent_id: str
    ticker: str
    side: str
    quantity: int
    limit_price: float
    estimated_notional_jpy: float
    nonce: str
    expected_account_fingerprint: str
    expected_commit_sha: str
    final_confirmation: str
    live_readonly_confirmation: str


@dataclass(frozen=True)
class LivePilotOperationalResult:
    status: str
    checked_at: str
    recovery_only: bool
    preflight_ready: bool
    send_status: str | None
    completion_status: str | None
    complete: bool
    blockers: tuple[str, ...]
    broker_connection_used: bool
    order_transport_called: bool
    automatic_retry_allowed: bool = False
    automatic_cancel_allowed: bool = False
    automatic_modify_allowed: bool = False
    automatic_flatten_allowed: bool = False
    automatic_close_allowed: bool = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _persist_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _resolve_presend_authorized_endpoint(
    request: LivePilotOperationalRequest,
) -> int:
    authorization = load_live_pilot_authorization_binding(
        nonce=request.nonce,
        intent_id=request.intent_id,
        ticker=request.ticker,
        side=request.side,
        quantity=request.quantity,
        limit_price=request.limit_price,
        estimated_notional_jpy=request.estimated_notional_jpy,
        account_fingerprint=request.expected_account_fingerprint,
    )
    endpoint_port = authorization.get("endpoint_port")
    if (
        not isinstance(endpoint_port, int)
        or isinstance(endpoint_port, bool)
        or endpoint_port not in {4001, 7496}
    ):
        raise PermissionError("active authorization endpoint binding is invalid")
    return endpoint_port


def _collect_presend_readonly_evidence(
    request: LivePilotOperationalRequest,
    *,
    authorized_endpoint_port: int,
) -> None:
    account = preview_ibkr_live_readonly_account_snapshot(
        confirmation=request.live_readonly_confirmation,
        endpoint_port=authorized_endpoint_port,
    )
    persist_live_readonly_account_snapshot(account)

    open_orders = preview_ibkr_live_all_open_orders(
        confirmation=request.live_readonly_confirmation,
        endpoint_port=authorized_endpoint_port,
    )
    persist_live_all_open_orders(open_orders)

    if request.ticker.strip().upper() in _USD_TICKERS:
        fx = resolve_ibkr_live_fx_evidence(
            base_currency="USD",
            quote_currency="JPY",
            confirmation=request.live_readonly_confirmation,
            endpoint_port=authorized_endpoint_port,
        )
        persist_live_fx_evidence(fx)


def _evaluate_and_persist_preflight(
    request: LivePilotOperationalRequest,
) -> tuple[dict, LivePilotSameRunPreflight]:
    readiness = audit_live_operational_pilot_readiness(
        ticker=request.ticker,
        side=request.side,
        quantity=request.quantity,
        estimated_notional_jpy=request.estimated_notional_jpy,
        expected_account_fingerprint=request.expected_account_fingerprint,
        limit_price=request.limit_price,
    )
    persist_live_operational_pilot_readiness(readiness)
    readiness_payload = readiness_record(readiness)

    account = _load_json(DEFAULT_LIVE_ACCOUNT_REPORT)
    open_orders = _load_json(DEFAULT_LIVE_OPEN_ORDERS_REPORT)
    fx = _load_json(DEFAULT_LIVE_FX_REPORT)
    paper = _load_json(DEFAULT_PAPER_MONITOR_REPORT)

    preflight = evaluate_live_pilot_same_run_preflight(
        ticker=request.ticker,
        expected_account_fingerprint=request.expected_account_fingerprint,
        readiness_report=readiness_payload,
        live_account_report=account,
        live_open_orders_report=open_orders,
        live_fx_report=fx,
        paper_monitor_report=paper,
    )
    _persist_json(DEFAULT_PREFLIGHT_REPORT, preflight_record(preflight))
    return readiness_payload, preflight


class _RecoveryEvidenceBindingError(PermissionError):
    """Persisted recovery identity is invalid before any broker collection."""


def _collect_post_attempt_readonly_evidence(
    request: LivePilotOperationalRequest,
) -> None:
    journal = load_send_journal(request.intent_id, directory=DEFAULT_JOURNAL_DIR)
    sender_client_id = (
        journal.get("sender_client_id") if isinstance(journal, dict) else None
    )
    authorized_endpoint_port = (
        journal.get("authorized_endpoint_port") if isinstance(journal, dict) else None
    )
    if (
        not isinstance(sender_client_id, int)
        or isinstance(sender_client_id, bool)
        or sender_client_id < 0
    ):
        raise _RecoveryEvidenceBindingError(
            "durable sender client_id is missing or invalid"
        )
    if (
        not isinstance(authorized_endpoint_port, int)
        or isinstance(authorized_endpoint_port, bool)
        or authorized_endpoint_port not in {4001, 7496}
    ):
        raise _RecoveryEvidenceBindingError(
            "durable authorized Live endpoint is missing or invalid"
        )
    postfill = preview_ibkr_live_postfill_snapshot(
        confirmation=request.live_readonly_confirmation,
        expected_client_id=sender_client_id,
        endpoint_port=authorized_endpoint_port,
    )
    persist_live_postfill_snapshot(postfill)

    account = preview_ibkr_live_readonly_account_snapshot(
        confirmation=request.live_readonly_confirmation,
        endpoint_port=authorized_endpoint_port,
    )
    persist_live_readonly_account_snapshot(account)

    open_orders = preview_ibkr_live_all_open_orders(
        confirmation=request.live_readonly_confirmation,
        endpoint_port=authorized_endpoint_port,
    )
    persist_live_all_open_orders(open_orders)

    completed_orders = preview_ibkr_live_completed_orders(
        confirmation=request.live_readonly_confirmation,
        endpoint_port=authorized_endpoint_port,
    )
    persist_live_completed_orders(completed_orders)


def _positive_exact_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


def _nonnegative_exact_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _positive_finite_number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def _request_matches_durable_authorization(
    request: LivePilotOperationalRequest,
    journal: dict | None,
) -> bool:
    """Bind every recovery pass to the exact consumed one-shot authorization."""
    if not isinstance(journal, dict):
        return False
    quantity = journal.get("authorized_quantity")
    limit_price = _positive_finite_number(journal.get("authorized_limit_price"))
    notional = _positive_finite_number(
        journal.get("authorized_estimated_notional_jpy")
    )
    endpoint_port = journal.get("authorized_endpoint_port")
    return bool(
        str(journal.get("intent_id") or "").strip() == request.intent_id.strip()
        and str(journal.get("nonce") or "").strip() == request.nonce.strip()
        and str(journal.get("authorized_ticker") or "").strip().upper()
        == request.ticker.strip().upper()
        and str(journal.get("authorized_side") or "").strip().upper()
        == request.side.strip().upper()
        and isinstance(quantity, int)
        and not isinstance(quantity, bool)
        and quantity == request.quantity
        and limit_price is not None
        and limit_price == float(request.limit_price)
        and notional is not None
        and notional == float(request.estimated_notional_jpy)
        and str(
            journal.get("authorized_account_fingerprint") or ""
        ).strip().lower()
        == request.expected_account_fingerprint.strip().lower()
        and isinstance(endpoint_port, int)
        and not isinstance(endpoint_port, bool)
        and endpoint_port in {4001, 7496}
    )


def _promote_postfill_if_proven(request: LivePilotOperationalRequest) -> None:
    journal = load_send_journal(request.intent_id, directory=DEFAULT_JOURNAL_DIR)
    if not isinstance(journal, dict):
        return
    if not _request_matches_durable_authorization(request, journal):
        return

    state = journal.get("state")
    if state not in {
        "SEND_ATTEMPT_RECORDED",
        "ORDER_ACKNOWLEDGED",
        "UNKNOWN",
        "POSTFILL_PROVEN",
    }:
        return

    # Persisted broker identity is itself a safety boundary. Reject malformed
    # journal values before reading any post-fill evidence.
    order_id = _positive_exact_int(journal.get("order_id"))
    if order_id is None:
        return
    sender_client_id = _nonnegative_exact_int(journal.get("sender_client_id"))
    if sender_client_id is None:
        return
    raw_perm_id = journal.get("perm_id")
    if raw_perm_id is None:
        perm_id = None
    else:
        perm_id = _positive_exact_int(raw_perm_id)
        if perm_id is None:
            return

    # Every fresh recovery report must pass exact broker-identity typing even
    # after POSTFILL_PROVEN. A later malformed report must never become
    # COMPLETE merely because an earlier pass had already promoted the journal.
    postfill_payload = _load_json(DEFAULT_POSTFILL_REPORT)
    if not isinstance(postfill_payload, dict):
        return
    rows = postfill_payload.get("executions")
    rows = rows if isinstance(rows, list) else []
    for row in rows:
        if not isinstance(row, dict):
            return
        if (
            _positive_exact_int(row.get("order_id")) is None
            or _positive_exact_int(row.get("perm_id")) is None
            or _nonnegative_exact_int(row.get("client_id")) is None
            or row.get("client_id") != sender_client_id
        ):
            return

    if state == "POSTFILL_PROVEN":
        if perm_id is None:
            return
        for row in rows:
            row_order_id = _positive_exact_int(row.get("order_id"))
            row_perm_id = _positive_exact_int(row.get("perm_id"))
            row_client_id = _nonnegative_exact_int(row.get("client_id"))
            if (
                row_order_id is None
                or row_perm_id is None
                or row_client_id != sender_client_id
            ):
                return
            if row_order_id == order_id and row_perm_id != perm_id:
                return
            if row_perm_id == perm_id and row_order_id != order_id:
                return
        return

    # SEND_ATTEMPT_RECORDED is intentionally recoverable here. A crash can
    # occur after placeOrder returns but before ACK/UNKNOWN is durably written.
    # The campaign marker still makes the sender unreachable; only fresh
    # read-only execution evidence may advance the journal.

    expected_symbol = (
        "9432"
        if request.ticker.strip().upper() == "9432.T"
        else request.ticker.strip().upper()
    )
    expected_side = request.side.strip().upper()
    expected_fingerprint = request.expected_account_fingerprint.strip().lower()

    if perm_id is None:
        same_order: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_order_id = _positive_exact_int(row.get("order_id"))
            if row_order_id == order_id:
                same_order.append(row)

        if not same_order:
            return
        for row in same_order:
            if (
                str(row.get("symbol") or "").strip().upper() != expected_symbol
                or str(row.get("sec_type") or "").strip().upper() != "STK"
                or str(row.get("side") or "").strip().upper() != expected_side
                or str(row.get("account_fingerprint") or "").strip().lower()
                != expected_fingerprint
            ):
                return

        candidate_perm_ids: set[int] = set()
        for row in same_order:
            candidate = _positive_exact_int(row.get("perm_id"))
            if candidate is None:
                return
            candidate_perm_ids.add(candidate)
        if len(candidate_perm_ids) != 1:
            return
        perm_id = next(iter(candidate_perm_ids))

    # Broker identity must be one-to-one in both directions. Reject any
    # contradictory or type-invalid row that claims either side of the chosen
    # (order_id, perm_id) pair instead of letting the shared matcher filter it
    # away. This keeps UNKNOWN/crash recovery fail-closed.
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_order_id = row.get("order_id")
        raw_perm_id = row.get("perm_id")
        row_order_id = _positive_exact_int(raw_order_id)
        row_perm_id = _positive_exact_int(raw_perm_id)

        # Broker execution identity is a safety boundary. Any type-invalid or
        # non-positive order_id/perm_id anywhere in the read-only execution
        # evidence makes the whole reconciliation ambiguous and therefore
        # fails closed, even when the malformed row would otherwise be
        # unrelated to the selected pair. This deliberately avoids trying to
        # enumerate every numeric string/float alias such as "+77",
        # "880077.0", scientific notation, or booleans.
        if row_order_id is None or row_perm_id is None:
            return

        # Treat numeric-equivalent but non-exact representations as claims on
        # the selected broker identity too. For example, "880077" or
        # 880077.0 must not evade the reverse-identity conflict check merely
        # because _positive_exact_int correctly rejects their type.
        raw_perm_claims_selected = (
            raw_perm_id == perm_id
            or (
                isinstance(raw_perm_id, str)
                and raw_perm_id.strip() == str(perm_id)
            )
        )
        if raw_perm_claims_selected:
            if row_perm_id is None or row_order_id is None or row_order_id != order_id:
                return

        # Persisted orderId must never appear with another/malformed permId.
        # Numeric-but-type-invalid forms (for example 77.0 or "77") are also
        # treated as claims on the selected identity and therefore fail closed.
        raw_order_claims_selected = (
            raw_order_id == order_id
            or (
                isinstance(raw_order_id, str)
                and raw_order_id.strip() == str(order_id)
            )
        )
        if raw_order_claims_selected:
            if row_order_id is None or row_perm_id is None or row_perm_id != perm_id:
                return

    # Rehydrate only through the existing persisted report contract by asking
    # the shared matcher to prove the complete fill/commission/account identity
    # before the durable journal can advance.
    from ai_asset_platform.brokers.ibkr_live_postfill_evidence import (
        IbkrLivePostFillSnapshot,
        LiveCommissionEvidence,
        LiveExecutionEvidence,
    )

    try:
        executions = tuple(
            LiveExecutionEvidence(**row)
            for row in rows
            if isinstance(row, dict)
        )
        commissions = tuple(
            LiveCommissionEvidence(**row)
            for row in postfill_payload.get("commissions", [])
            if isinstance(row, dict)
        )
    except (TypeError, ValueError):
        return

    snapshot = IbkrLivePostFillSnapshot(
        attempted=postfill_payload.get("attempted") is True,
        connected=postfill_payload.get("connected") is True,
        endpoint_port=postfill_payload.get("endpoint_port"),
        account_fingerprint=postfill_payload.get("account_fingerprint"),
        executions=executions,
        commissions=commissions,
        blocked_reason=postfill_payload.get("blocked_reason"),
        errors=tuple(postfill_payload.get("errors") or ()),
    )
    matched = match_live_postfill(
        snapshot,
        expected_account_fingerprint=request.expected_account_fingerprint,
        ticker=request.ticker,
        side=request.side,
        quantity=request.quantity,
        order_id=order_id,
        perm_id=perm_id,
        expected_client_id=sender_client_id,
    )
    if not matched.ready or not matched.executions:
        return

    mark_postfill_proven(
        request.intent_id,
        exec_id=matched.executions[0].exec_id,
        order_id=order_id,
        perm_id=perm_id,
        directory=DEFAULT_JOURNAL_DIR,
    )



def _finite_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _definitive_rejection_reason(value: object) -> str | None:
    reason = str(value or "").strip()
    for prefix in (
        "broker orderStatus callback reported non-accepted status:",
        "broker openOrder callback reported non-accepted status:",
        "broker completedOrder callback reported terminal status:",
    ):
        if reason.startswith(prefix):
            status = reason[len(prefix) :].strip()
            return reason if status in _DEFINITIVE_REJECTION_STATUSES else None

    parts = reason.split(":", 2)
    if (
        len(parts) == 3
        and parts[0].isdigit()
        and parts[1].isdigit()
        and int(parts[1]) in _DEFINITIVE_REJECTION_ERROR_CODES
    ):
        return reason
    return None


def _terminal_reconciliation_is_durably_proven(
    request: LivePilotOperationalRequest,
    journal: dict,
    terminal: dict,
) -> bool:
    """Validate immutable terminal proof plus both irreversible attempt markers."""
    state = terminal.get("state")
    if state not in {"PARTIAL_RECONCILED", "REJECTED_RECONCILED"}:
        return False
    if (
        terminal.get("schema_version") != SEND_JOURNAL_SCHEMA_VERSION
        or terminal.get("send_attempt_count") != 1
        or isinstance(terminal.get("send_attempt_count"), bool)
        or terminal.get("recovery_required") is not False
        or terminal.get("order_sent") is not False
        or terminal.get("live_order_sent") is not False
    ):
        return False
    for flag in (
        "automatic_resend_allowed",
        "automatic_cancel_allowed",
        "automatic_modify_allowed",
        "automatic_flatten_allowed",
        "automatic_close_allowed",
    ):
        if terminal.get(flag) is not False:
            return False

    # The independent terminal marker carries the original consumed
    # authorization binding so a later edit/restore of the mutable summary
    # journal cannot redefine what the pilot was allowed to do.
    quantity = terminal.get("authorized_quantity")
    limit_price = _positive_finite_number(terminal.get("authorized_limit_price"))
    notional = _positive_finite_number(
        terminal.get("authorized_estimated_notional_jpy")
    )
    endpoint_port = terminal.get("authorized_endpoint_port")
    if not (
        str(terminal.get("intent_id") or "").strip() == request.intent_id.strip()
        and str(terminal.get("nonce") or "").strip() == request.nonce.strip()
        and str(terminal.get("authorized_ticker") or "").strip().upper()
        == request.ticker.strip().upper()
        and str(terminal.get("authorized_side") or "").strip().upper()
        == request.side.strip().upper()
        and isinstance(quantity, int)
        and not isinstance(quantity, bool)
        and quantity == request.quantity
        and limit_price is not None
        and limit_price == float(request.limit_price)
        and notional is not None
        and notional == float(request.estimated_notional_jpy)
        and str(
            terminal.get("authorized_account_fingerprint") or ""
        ).strip().lower()
        == request.expected_account_fingerprint.strip().lower()
        and isinstance(endpoint_port, int)
        and not isinstance(endpoint_port, bool)
        and endpoint_port in {4001, 7496}
    ):
        return False

    # A terminal summary may legitimately lag the exclusive marker if the
    # process crashed between marker creation and summary replacement.  But a
    # summary that already claims a terminal state must agree with the marker.
    journal_state = journal.get("state") if isinstance(journal, dict) else None
    if journal_state in {"PARTIAL_RECONCILED", "REJECTED_RECONCILED"}:
        if journal_state != state:
            return False
    if not isinstance(journal, dict) or journal.get("send_attempt_count") != 1:
        return False
    if isinstance(journal.get("send_attempt_count"), bool):
        return False

    order_id = _positive_exact_int(terminal.get("order_id"))
    sender_client_id = _nonnegative_exact_int(terminal.get("sender_client_id"))
    if order_id is None or sender_client_id is None:
        return False
    journal_order_id = journal.get("order_id")
    journal_sender_client_id = journal.get("sender_client_id")
    if journal_order_id is not None:
        if (
            _positive_exact_int(journal_order_id) is None
            or journal_order_id != order_id
        ):
            return False
    if journal_sender_client_id is not None:
        if (
            _nonnegative_exact_int(journal_sender_client_id) is None
            or journal_sender_client_id != sender_client_id
        ):
            return False

    try:
        attempt = load_send_attempt_marker(
            request.intent_id,
            directory=DEFAULT_JOURNAL_DIR,
        )
        global_attempt = load_global_send_attempt_marker(
            directory=DEFAULT_JOURNAL_DIR
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(attempt, dict) or not isinstance(global_attempt, dict):
        return False
    if (
        attempt.get("schema_version") != SEND_JOURNAL_SCHEMA_VERSION
        or global_attempt.get("schema_version") != SEND_JOURNAL_SCHEMA_VERSION
        or attempt.get("state") != "SEND_ATTEMPT_RECORDED"
        or str(attempt.get("intent_id") or "") != request.intent_id
        or str(global_attempt.get("intent_id") or "") != request.intent_id
        or str(attempt.get("nonce") or "") != request.nonce
        or attempt.get("automatic_resend_allowed") is not False
        or global_attempt.get("automatic_resend_allowed") is not False
    ):
        return False
    for flag in (
        "automatic_cancel_allowed",
        "automatic_modify_allowed",
        "automatic_flatten_allowed",
        "automatic_close_allowed",
    ):
        if attempt.get(flag) is not False:
            return False

    attempt_time = _parse_aware_timestamp(attempt.get("recorded_at"))
    global_time = _parse_aware_timestamp(global_attempt.get("recorded_at"))
    terminal_attempt_time = _parse_aware_timestamp(
        terminal.get("send_attempt_recorded_at")
    )
    terminal_time = _parse_aware_timestamp(terminal.get("terminal_recorded_at"))
    if (
        attempt_time is None
        or global_time is None
        or terminal_attempt_time is None
        or terminal_time is None
        or global_time != attempt_time
        or terminal_attempt_time != attempt_time
        or terminal_time < attempt_time
    ):
        return False

    expected_side = request.side.strip().upper()
    authorized_quantity = Decimal(request.quantity)
    final_position = _finite_decimal(terminal.get("final_position_quantity"))
    if final_position is None:
        return False

    if state == "PARTIAL_RECONCILED":
        perm_id = _positive_exact_int(terminal.get("perm_id"))
        exec_ids = terminal.get("exec_ids")
        filled_quantity = _finite_decimal(terminal.get("filled_quantity"))
        commission_total = _finite_decimal(terminal.get("commission_total"))
        expected_currency = (
            "JPY" if request.ticker.strip().upper() == "9432.T" else "USD"
        )
        if (
            perm_id is None
            or not isinstance(exec_ids, list)
            or not exec_ids
            or any(
                not isinstance(value, str) or not value.strip()
                for value in exec_ids
            )
            or len(exec_ids) != len(set(exec_ids))
            or filled_quantity is None
            or filled_quantity <= 0
            or filled_quantity >= authorized_quantity
            or commission_total is None
            or str(terminal.get("commission_currency") or "").strip().upper()
            != expected_currency
        ):
            return False
        expected_final = (
            filled_quantity
            if expected_side == "BUY"
            else authorized_quantity - filled_quantity
        )
        return final_position == expected_final

    raw_terminal_perm = terminal.get("perm_id")
    if raw_terminal_perm is None:
        terminal_perm = None
    else:
        terminal_perm = _positive_exact_int(raw_terminal_perm)
        if terminal_perm is None:
            return False
    raw_journal_perm = journal.get("perm_id")
    if raw_journal_perm is None:
        if terminal_perm is not None:
            return False
    else:
        journal_perm = _positive_exact_int(raw_journal_perm)
        if journal_perm is None or journal_perm != terminal_perm:
            return False

    rejection_reason = _definitive_rejection_reason(
        terminal.get("rejection_reason")
    )
    if rejection_reason is None:
        return False
    try:
        rejection_evidence = load_definitive_rejection_evidence(
            request.intent_id,
            directory=DEFAULT_JOURNAL_DIR,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(rejection_evidence, dict):
        return False
    rejection_attempt_time = _parse_aware_timestamp(
        rejection_evidence.get("send_attempt_recorded_at")
    )
    rejection_recorded_time = _parse_aware_timestamp(
        rejection_evidence.get("rejection_recorded_at")
    )
    if (
        rejection_evidence.get("schema_version") != SEND_JOURNAL_SCHEMA_VERSION
        or str(rejection_evidence.get("intent_id") or "") != request.intent_id
        or str(rejection_evidence.get("nonce") or "") != request.nonce
        or str(rejection_evidence.get("ticker") or "").strip().upper()
        != request.ticker.strip().upper()
        or str(rejection_evidence.get("side") or "").strip().upper()
        != request.side.strip().upper()
        or rejection_evidence.get("quantity") != request.quantity
        or isinstance(rejection_evidence.get("quantity"), bool)
        or _positive_finite_number(rejection_evidence.get("limit_price"))
        != float(request.limit_price)
        or _positive_finite_number(
            rejection_evidence.get("estimated_notional_jpy")
        )
        != float(request.estimated_notional_jpy)
        or str(rejection_evidence.get("account_fingerprint") or "").strip().lower()
        != request.expected_account_fingerprint.strip().lower()
        or rejection_evidence.get("endpoint_port") != endpoint_port
        or isinstance(rejection_evidence.get("endpoint_port"), bool)
        or _positive_exact_int(rejection_evidence.get("order_id")) != order_id
        or rejection_evidence.get("perm_id") != terminal_perm
        or _nonnegative_exact_int(rejection_evidence.get("sender_client_id"))
        != sender_client_id
        or _definitive_rejection_reason(
            rejection_evidence.get("rejection_reason")
        )
        != rejection_reason
        or rejection_attempt_time != attempt_time
        or rejection_recorded_time is None
        or rejection_recorded_time < attempt_time
    ):
        return False
    for flag in (
        "automatic_resend_allowed",
        "automatic_cancel_allowed",
        "automatic_modify_allowed",
        "automatic_flatten_allowed",
        "automatic_close_allowed",
        "order_sent",
        "live_order_sent",
    ):
        if rejection_evidence.get(flag) is not False:
            return False

    expected_final = Decimal("0") if expected_side == "BUY" else authorized_quantity
    return final_position == expected_final

def _completed_order_rejection_if_proven(
    request: LivePilotOperationalRequest,
    journal: dict,
    completed: dict,
    *,
    endpoint_port: int,
    order_id: int,
    sender_client_id: int,
    now: datetime,
) -> tuple[str, int] | None:
    """Return exact terminal rejection reason/permId from fresh Live history.

    This is read-only recovery evidence for the case where an acknowledged
    order is cancelled after the sender has disconnected.  Every durable and
    broker identity field must agree; ambiguity remains UNKNOWN.
    """
    if not _clean_live_report(
        completed,
        required_schema_version=LIVE_COMPLETED_ORDERS_SCHEMA_VERSION,
        required_false_flags=(
            "order_sent",
            "cancel_sent",
            "modify_sent",
            "live_order_sent",
        ),
    ):
        return None
    if not _fresh(
        completed,
        now=now,
        max_age_seconds=DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
    ):
        return None
    fingerprint = request.expected_account_fingerprint.strip().lower()
    if (
        completed.get("endpoint_port") != endpoint_port
        or isinstance(completed.get("endpoint_port"), bool)
        or str(completed.get("account_fingerprint") or "").strip().lower()
        != fingerprint
        or completed.get("raw_account_id_persisted") is not False
    ):
        return None

    orders = completed.get("orders")
    count = completed.get("completed_order_count")
    if (
        not isinstance(orders, list)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        or count != len(orders)
    ):
        return None

    parsed_rows: list[tuple[dict, int, int, int]] = []
    for row in orders:
        if not isinstance(row, dict):
            return None
        row_order = _positive_exact_int(row.get("order_id"))
        row_perm = _positive_exact_int(row.get("perm_id"))
        row_client = _nonnegative_exact_int(row.get("client_id"))
        if row_order is None or row_perm is None or row_client is None:
            return None
        parsed_rows.append((row, row_order, row_perm, row_client))

    matching = [
        item
        for item in parsed_rows
        if item[1] == order_id and item[3] == sender_client_id
    ]
    if len(matching) != 1:
        return None
    row, _, row_perm, row_client = matching[0]
    if row_client != sender_client_id:
        return None

    raw_persisted_perm = journal.get("perm_id")
    if raw_persisted_perm is not None:
        persisted_perm = _positive_exact_int(raw_persisted_perm)
        if persisted_perm is None or persisted_perm != row_perm:
            return None
    if any(
        other_perm == row_perm and other_order != order_id
        for _, other_order, other_perm, _ in parsed_rows
    ):
        return None

    expected_symbol = (
        "9432"
        if request.ticker.strip().upper() == "9432.T"
        else request.ticker.strip().upper()
    )
    expected_currency = (
        "JPY" if request.ticker.strip().upper() == "9432.T" else "USD"
    )
    quantity = _positive_finite_number(row.get("quantity"))
    limit_price = _positive_finite_number(row.get("limit_price"))
    if (
        str(row.get("symbol") or "").strip().upper() != expected_symbol
        or str(row.get("sec_type") or "").strip().upper() != "STK"
        or str(row.get("currency") or "").strip().upper() != expected_currency
        or str(row.get("action") or "").strip().upper()
        != request.side.strip().upper()
        or quantity != float(request.quantity)
        or str(row.get("order_type") or "").strip().upper() != "LMT"
        or limit_price != float(request.limit_price)
        or str(row.get("order_ref") or "").strip() != request.intent_id
        or str(row.get("account_fingerprint") or "").strip().lower()
        != fingerprint
    ):
        return None

    statuses = [
        str(row.get(name) or "").strip()
        for name in ("status", "completed_status")
        if str(row.get(name) or "").strip()
    ]
    if not statuses or any(
        status not in _DEFINITIVE_REJECTION_STATUSES for status in statuses
    ):
        return None
    status = statuses[-1]
    return (
        f"broker completedOrder callback reported terminal status: {status}",
        row_perm,
    )


def _promote_terminal_reconciliation_if_proven(
    request: LivePilotOperationalRequest,
) -> str | None:
    """Promote only fully reconciled no-retry terminal non-full-fill outcomes.

    A partial fill or explicit broker rejection is terminal evidence for this
    one-shot campaign, not permission to send a remainder or retry.
    """
    journal = load_send_journal(request.intent_id, directory=DEFAULT_JOURNAL_DIR)
    if not _request_matches_durable_authorization(request, journal):
        return None
    if not isinstance(journal, dict) or journal.get("state") not in {
        "SEND_ATTEMPT_RECORDED",
        "ORDER_ACKNOWLEDGED",
        "UNKNOWN",
    }:
        return None

    order_id = _positive_exact_int(journal.get("order_id"))
    sender_client_id = _nonnegative_exact_int(journal.get("sender_client_id"))
    endpoint_port = journal.get("authorized_endpoint_port")
    if (
        order_id is None
        or sender_client_id is None
        or not isinstance(endpoint_port, int)
        or isinstance(endpoint_port, bool)
        or endpoint_port not in {4001, 7496}
    ):
        return None

    postfill = _load_json(DEFAULT_POSTFILL_REPORT)
    account = _load_json(DEFAULT_LIVE_ACCOUNT_REPORT)
    open_orders = _load_json(DEFAULT_LIVE_OPEN_ORDERS_REPORT)
    paper = _load_json(DEFAULT_PAPER_MONITOR_REPORT)
    attempt_marker = load_send_attempt_marker(
        request.intent_id, directory=DEFAULT_JOURNAL_DIR
    )
    if not all(
        isinstance(report, dict)
        for report in (postfill, account, open_orders, paper, attempt_marker)
    ):
        return None

    current = _utc_now()
    if not (
        _fresh(
            postfill,
            now=current,
            max_age_seconds=DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
        )
        and _fresh(
            account,
            now=current,
            max_age_seconds=DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
        )
        and _fresh(
            open_orders,
            now=current,
            max_age_seconds=DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
        )
        and _fresh(
            paper,
            now=current,
            max_age_seconds=DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
        )
    ):
        return None

    marker_time = _parse_aware_timestamp(attempt_marker.get("recorded_at"))
    paper_time = _parse_aware_timestamp(paper.get("checked_at"))
    if marker_time is None or paper_time is None or paper_time <= marker_time:
        return None
    if not _paper_safe(paper):
        return None

    if not _clean_live_report(
        postfill,
        required_schema_version=LIVE_POSTFILL_SCHEMA_VERSION,
        required_false_flags=("order_sent", "live_order_sent"),
    ):
        return None
    if not _clean_live_report(
        account,
        required_schema_version=LIVE_ACCOUNT_SCHEMA_VERSION,
        required_false_flags=("order_sent", "live_order_sent"),
    ):
        return None
    if not _clean_live_report(
        open_orders,
        required_schema_version=LIVE_OPEN_ORDERS_SCHEMA_VERSION,
        required_false_flags=("order_sent", "cancel_sent", "live_order_sent"),
    ):
        return None

    fingerprint = request.expected_account_fingerprint.strip().lower()
    for report in (postfill, account, open_orders):
        if report.get("endpoint_port") != endpoint_port:
            return None
        if str(report.get("account_fingerprint") or "").strip().lower() != fingerprint:
            return None

    if (
        open_orders.get("open_order_count") != 0
        or isinstance(open_orders.get("open_order_count"), bool)
        or not isinstance(open_orders.get("orders"), list)
        or open_orders.get("orders")
    ):
        return None

    rows = postfill.get("executions")
    commissions = postfill.get("commissions")
    if not isinstance(rows, list) or not isinstance(commissions, list):
        return None

    validated_rows: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        row_order = _positive_exact_int(row.get("order_id"))
        row_perm = _positive_exact_int(row.get("perm_id"))
        row_client = _nonnegative_exact_int(row.get("client_id"))
        if row_order is None or row_perm is None or row_client != sender_client_id:
            return None
        validated_rows.append(row)

    selected_rows = [
        row for row in validated_rows if row.get("order_id") == order_id
    ]
    raw_persisted_perm = journal.get("perm_id")
    if raw_persisted_perm is None:
        persisted_perm = None
    else:
        persisted_perm = _positive_exact_int(raw_persisted_perm)
        if persisted_perm is None:
            return None
    if selected_rows:
        selected_perm_ids = {row.get("perm_id") for row in selected_rows}
        if len(selected_perm_ids) != 1:
            return None
        selected_perm = next(iter(selected_perm_ids))
        if persisted_perm is not None and selected_perm != persisted_perm:
            return None
        if any(
            row.get("perm_id") == selected_perm and row.get("order_id") != order_id
            for row in validated_rows
        ):
            return None

        expected_symbol = (
            "9432"
            if request.ticker.strip().upper() == "9432.T"
            else request.ticker.strip().upper()
        )
        expected_side = request.side.strip().upper()
        expected_currency = "JPY" if request.ticker.strip().upper() == "9432.T" else "USD"
        total_quantity = Decimal("0")
        exec_ids: list[str] = []
        commission_total = Decimal("0")
        for row in selected_rows:
            if (
                str(row.get("symbol") or "").strip().upper() != expected_symbol
                or str(row.get("sec_type") or "").strip().upper() != "STK"
                or str(row.get("side") or "").strip().upper() != expected_side
                or str(row.get("currency") or "").strip().upper() != expected_currency
                or str(row.get("account_fingerprint") or "").strip().lower()
                != fingerprint
            ):
                return None
            quantity = _finite_decimal(row.get("quantity"))
            price = _finite_decimal(row.get("price"))
            exec_id = str(row.get("exec_id") or "").strip()
            if (
                quantity is None
                or quantity <= 0
                or price is None
                or price <= 0
                or not exec_id
            ):
                return None
            try:
                total_quantity += quantity
            except ArithmeticError:
                return None
            exec_ids.append(exec_id)

        if len(exec_ids) != len(set(exec_ids)):
            return None
        authorized_quantity = Decimal(request.quantity)
        if total_quantity <= 0 or total_quantity >= authorized_quantity:
            return None

        for exec_id in exec_ids:
            matched_commissions = [
                row
                for row in commissions
                if isinstance(row, dict)
                and str(row.get("exec_id") or "").strip() == exec_id
            ]
            if len(matched_commissions) != 1:
                return None
            commission_row = matched_commissions[0]
            value = _finite_decimal(commission_row.get("commission"))
            currency = str(commission_row.get("currency") or "").strip().upper()
            if value is None or currency != expected_currency:
                return None
            try:
                commission_total += value
            except ArithmeticError:
                return None

        final_position = _target_position_quantity(account, request.ticker)
        expected_final_position = (
            float(total_quantity)
            if expected_side == "BUY"
            else float(authorized_quantity - total_quantity)
        )
        if final_position is None or final_position != expected_final_position:
            return None

        mark_partial_reconciled(
            request.intent_id,
            exec_ids=tuple(exec_ids),
            order_id=order_id,
            perm_id=int(selected_perm),
            filled_quantity=float(total_quantity),
            commission_total=float(commission_total),
            commission_currency=expected_currency,
            final_position_quantity=final_position,
            directory=DEFAULT_JOURNAL_DIR,
        )
        return "PARTIAL_RECONCILED"

    # No matching execution rows: only an explicit broker-side non-acceptance
    # may become REJECTED_RECONCILED. Timeout/disconnect/no-evidence remains
    # UNKNOWN by design.
    try:
        rejection_evidence = load_definitive_rejection_evidence(
            request.intent_id,
            directory=DEFAULT_JOURNAL_DIR,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(rejection_evidence, dict):
        try:
            completed = _load_json(DEFAULT_LIVE_COMPLETED_ORDERS_REPORT)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(completed, dict):
            return None
        completed_rejection = _completed_order_rejection_if_proven(
            request,
            journal,
            completed,
            endpoint_port=endpoint_port,
            order_id=order_id,
            sender_client_id=sender_client_id,
            now=current,
        )
        if completed_rejection is None:
            return None
        completed_reason, completed_perm = completed_rejection
        try:
            rejection_evidence = record_definitive_rejection_evidence(
                request.intent_id,
                nonce=request.nonce,
                ticker=request.ticker,
                side=request.side,
                quantity=request.quantity,
                limit_price=request.limit_price,
                estimated_notional_jpy=request.estimated_notional_jpy,
                account_fingerprint=request.expected_account_fingerprint,
                endpoint_port=endpoint_port,
                order_id=order_id,
                client_id=sender_client_id,
                rejection_reason=completed_reason,
                perm_id=completed_perm,
                directory=DEFAULT_JOURNAL_DIR,
            )
        except (OSError, UnicodeError, ValueError, PermissionError):
            return None

    rejection_reason = _definitive_rejection_reason(
        rejection_evidence.get("rejection_reason")
    )
    rejection_attempt_time = _parse_aware_timestamp(
        rejection_evidence.get("send_attempt_recorded_at")
    )
    rejection_recorded_time = _parse_aware_timestamp(
        rejection_evidence.get("rejection_recorded_at")
    )
    marker_time = _parse_aware_timestamp(attempt_marker.get("recorded_at"))
    if (
        rejection_reason is None
        or rejection_evidence.get("schema_version") != SEND_JOURNAL_SCHEMA_VERSION
        or str(rejection_evidence.get("intent_id") or "") != request.intent_id
        or str(rejection_evidence.get("nonce") or "") != request.nonce
        or str(rejection_evidence.get("ticker") or "").strip().upper()
        != request.ticker.strip().upper()
        or str(rejection_evidence.get("side") or "").strip().upper()
        != request.side.strip().upper()
        or rejection_evidence.get("quantity") != request.quantity
        or isinstance(rejection_evidence.get("quantity"), bool)
        or _positive_finite_number(rejection_evidence.get("limit_price"))
        != float(request.limit_price)
        or _positive_finite_number(
            rejection_evidence.get("estimated_notional_jpy")
        )
        != float(request.estimated_notional_jpy)
        or str(rejection_evidence.get("account_fingerprint") or "").strip().lower()
        != request.expected_account_fingerprint.strip().lower()
        or rejection_evidence.get("endpoint_port") != endpoint_port
        or isinstance(rejection_evidence.get("endpoint_port"), bool)
        or _positive_exact_int(rejection_evidence.get("order_id")) != order_id
        or _nonnegative_exact_int(rejection_evidence.get("sender_client_id"))
        != sender_client_id
        or marker_time is None
        or rejection_attempt_time != marker_time
        or rejection_recorded_time is None
        or rejection_recorded_time < marker_time
    ):
        return None
    for flag in (
        "automatic_resend_allowed",
        "automatic_cancel_allowed",
        "automatic_modify_allowed",
        "automatic_flatten_allowed",
        "automatic_close_allowed",
        "order_sent",
        "live_order_sent",
    ):
        if rejection_evidence.get(flag) is not False:
            return None
    raw_rejection_perm = rejection_evidence.get("perm_id")
    if raw_rejection_perm is None:
        rejection_perm = None
    else:
        rejection_perm = _positive_exact_int(raw_rejection_perm)
        if rejection_perm is None:
            return None
    if persisted_perm != rejection_perm:
        return None
    if any(row.get("order_id") == order_id for row in validated_rows):
        return None

    final_position = _target_position_quantity(account, request.ticker)
    expected_unchanged_position = (
        0.0 if request.side.strip().upper() == "BUY" else float(request.quantity)
    )
    if final_position is None or final_position != expected_unchanged_position:
        return None

    mark_rejected_reconciled(
        request.intent_id,
        rejection_reason=rejection_reason,
        order_id=order_id,
        final_position_quantity=final_position,
        perm_id=rejection_perm,
        directory=DEFAULT_JOURNAL_DIR,
    )
    return "REJECTED_RECONCILED"


def _reconcile_once(
    request: LivePilotOperationalRequest,
    *,
    send_status: str | None,
    order_transport_called: bool,
) -> LivePilotOperationalResult:
    try:
        journal = load_send_journal(
            request.intent_id,
            directory=DEFAULT_JOURNAL_DIR,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return LivePilotOperationalResult(
            status="BLOCKED_TERMINAL_EVIDENCE",
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=True,
            preflight_ready=False,
            send_status=send_status,
            completion_status=None,
            complete=False,
            blockers=(f"durable send journal is unreadable: {exc}",),
            broker_connection_used=False,
            order_transport_called=order_transport_called,
        )
    if not _request_matches_durable_authorization(request, journal):
        return LivePilotOperationalResult(
            status="BLOCKED_AUTHORIZATION_BINDING",
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=True,
            preflight_ready=False,
            send_status=send_status,
            completion_status=None,
            complete=False,
            blockers=(
                "recovery request does not match the durable consumed authorization",
            ),
            broker_connection_used=False,
            order_transport_called=order_transport_called,
        )

    terminal_state = journal.get("state") if isinstance(journal, dict) else None
    try:
        terminal = load_terminal_reconciliation_marker(
            request.intent_id,
            directory=DEFAULT_JOURNAL_DIR,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        terminal = {"state": "INVALID_TERMINAL_MARKER"}

    if terminal is not None:
        terminal_marker_state = (
            terminal.get("state") if isinstance(terminal, dict) else None
        )
        if not isinstance(terminal, dict) or not _terminal_reconciliation_is_durably_proven(
            request,
            journal,
            terminal,
        ):
            return LivePilotOperationalResult(
                status="BLOCKED_TERMINAL_EVIDENCE",
                checked_at=_utc_now().isoformat(timespec="seconds"),
                recovery_only=True,
                preflight_ready=False,
                send_status=send_status,
                completion_status=terminal_marker_state,
                complete=False,
                blockers=(
                    "exclusive terminal reconciliation evidence is incomplete or invalid",
                ),
                broker_connection_used=False,
                order_transport_called=order_transport_called,
            )
        terminal_marker_state = str(terminal.get("state"))
        return LivePilotOperationalResult(
            status=terminal_marker_state,
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=True,
            preflight_ready=False,
            send_status=send_status,
            completion_status=terminal_marker_state,
            complete=True,
            blockers=(),
            broker_connection_used=False,
            order_transport_called=order_transport_called,
        )

    if terminal_state in {"PARTIAL_RECONCILED", "REJECTED_RECONCILED"}:
        return LivePilotOperationalResult(
            status="BLOCKED_TERMINAL_EVIDENCE",
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=True,
            preflight_ready=False,
            send_status=send_status,
            completion_status=terminal_state,
            complete=False,
            blockers=("exclusive terminal reconciliation marker is missing",),
            broker_connection_used=False,
            order_transport_called=order_transport_called,
        )

    try:
        _collect_post_attempt_readonly_evidence(request)
    except _RecoveryEvidenceBindingError as exc:
        return LivePilotOperationalResult(
            status="BLOCKED_TERMINAL_EVIDENCE",
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=True,
            preflight_ready=False,
            send_status=send_status,
            completion_status=None,
            complete=False,
            blockers=(f"recovery broker identity is invalid: {exc}",),
            broker_connection_used=False,
            order_transport_called=order_transport_called,
        )

    try:
        _promote_postfill_if_proven(request)
        terminal_status = _promote_terminal_reconciliation_if_proven(request)
    except (PermissionError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return LivePilotOperationalResult(
            status="BLOCKED_TERMINAL_EVIDENCE",
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=True,
            preflight_ready=False,
            send_status=send_status,
            completion_status=None,
            complete=False,
            blockers=(
                "terminal reconciliation transition could not prove durable marker integrity",
            ),
            broker_connection_used=True,
            order_transport_called=order_transport_called,
        )
    if terminal_status is not None:
        try:
            refreshed_journal = load_send_journal(
                request.intent_id,
                directory=DEFAULT_JOURNAL_DIR,
            )
            terminal = load_terminal_reconciliation_marker(
                request.intent_id,
                directory=DEFAULT_JOURNAL_DIR,
            )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            refreshed_journal = None
            terminal = None
        if (
            not isinstance(refreshed_journal, dict)
            or not isinstance(terminal, dict)
            or terminal.get("state") != terminal_status
            or not _terminal_reconciliation_is_durably_proven(
                request,
                refreshed_journal,
                terminal,
            )
        ):
            return LivePilotOperationalResult(
                status="BLOCKED_TERMINAL_EVIDENCE",
                checked_at=_utc_now().isoformat(timespec="seconds"),
                recovery_only=True,
                preflight_ready=False,
                send_status=send_status,
                completion_status=terminal_status,
                complete=False,
                blockers=(
                    "new terminal reconciliation proof did not validate durably",
                ),
                broker_connection_used=True,
                order_transport_called=order_transport_called,
            )
        return LivePilotOperationalResult(
            status=terminal_status,
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=True,
            preflight_ready=False,
            send_status=send_status,
            completion_status=terminal_status,
            complete=True,
            blockers=(),
            broker_connection_used=True,
            order_transport_called=order_transport_called,
        )

    completion = audit_live_pilot_completion(
        intent_id=request.intent_id,
        ticker=request.ticker,
        side=request.side,
        quantity=request.quantity,
        expected_account_fingerprint=request.expected_account_fingerprint,
    )
    persist_live_pilot_completion(
        completion,
        report_path=DEFAULT_COMPLETION_REPORT,
        alert_path=DEFAULT_OPERATOR_ALERT,
    )

    return LivePilotOperationalResult(
        status="COMPLETE" if completion.complete else "RECOVERY_REQUIRED",
        checked_at=_utc_now().isoformat(timespec="seconds"),
        recovery_only=True,
        preflight_ready=False,
        send_status=send_status,
        completion_status=completion.status,
        complete=completion.complete,
        blockers=tuple(completion.blockers),
        broker_connection_used=True,
        order_transport_called=order_transport_called,
    )


def run_live_pilot_operational_once(
    request: LivePilotOperationalRequest,
    *,
    repository_root: Path = Path("."),
) -> LivePilotOperationalResult:
    """Run one fail-closed operational pass.

    The campaign-wide marker is checked before any path that can reach the
    sender.  Once it exists, every later invocation is recovery-only and can
    perform read-only reconciliation but can never reach the sender again.
    """
    if request.live_readonly_confirmation != LIVE_READONLY_CONFIRMATION_VALUE:
        return LivePilotOperationalResult(
            status="BLOCKED_READONLY_CONFIRMATION",
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=False,
            preflight_ready=False,
            send_status=None,
            completion_status=None,
            complete=False,
            blockers=("exact Live read-only confirmation is missing",),
            broker_connection_used=False,
            order_transport_called=False,
        )

    attempt_recorded = global_send_attempt_recorded(directory=DEFAULT_JOURNAL_DIR)
    if attempt_recorded:
        try:
            journal = load_send_journal(
                request.intent_id,
                directory=DEFAULT_JOURNAL_DIR,
            )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            return LivePilotOperationalResult(
                status="BLOCKED_TERMINAL_EVIDENCE",
                checked_at=_utc_now().isoformat(timespec="seconds"),
                recovery_only=True,
                preflight_ready=False,
                send_status=None,
                completion_status=None,
                complete=False,
                blockers=(f"durable send journal is unreadable: {exc}",),
                broker_connection_used=False,
                order_transport_called=False,
            )
        if not _request_matches_durable_authorization(request, journal):
            return LivePilotOperationalResult(
                status="BLOCKED_AUTHORIZATION_BINDING",
                checked_at=_utc_now().isoformat(timespec="seconds"),
                recovery_only=True,
                preflight_ready=False,
                send_status=None,
                completion_status=None,
                complete=False,
                blockers=(
                    "recovery request does not match the durable consumed authorization",
                ),
                broker_connection_used=False,
                order_transport_called=False,
            )

        # Recovery is safety-critical too. Verify the exact approved commit
        # and tracked cleanliness before any recovery broker collection or
        # completion persistence. The pre-send path is still audited again by
        # the existing sender immediately before transport.
        source = audit_live_pilot_source_cutover(
            expected_commit_sha=request.expected_commit_sha,
            repository_root=repository_root,
        )
        if not source.ready:
            return LivePilotOperationalResult(
                status="BLOCKED_SOURCE_CUTOVER",
                checked_at=_utc_now().isoformat(timespec="seconds"),
                recovery_only=True,
                preflight_ready=False,
                send_status=None,
                completion_status=None,
                complete=False,
                blockers=("audited source/PIN cutover is not ready",),
                broker_connection_used=False,
                order_transport_called=False,
            )
        return _reconcile_once(
            request,
            send_status=None,
            order_transport_called=False,
        )

    try:
        authorized_endpoint_port = _resolve_presend_authorized_endpoint(request)
    except (PermissionError, ValueError, TypeError) as exc:
        return LivePilotOperationalResult(
            status="BLOCKED_AUTHORIZATION_BINDING",
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=False,
            preflight_ready=False,
            send_status=None,
            completion_status=None,
            complete=False,
            blockers=(
                f"active one-shot authorization is not valid for pre-send collection: {exc}",
            ),
            broker_connection_used=False,
            order_transport_called=False,
        )

    _collect_presend_readonly_evidence(
        request,
        authorized_endpoint_port=authorized_endpoint_port,
    )
    readiness_payload, preflight = _evaluate_and_persist_preflight(request)
    if not preflight.ready:
        return LivePilotOperationalResult(
            status="BLOCKED_PREFLIGHT",
            checked_at=_utc_now().isoformat(timespec="seconds"),
            recovery_only=False,
            preflight_ready=False,
            send_status=None,
            completion_status=None,
            complete=False,
            blockers=tuple(preflight.blockers),
            broker_connection_used=True,
            order_transport_called=False,
        )

    send_request = LivePilotSendRequest(
        intent_id=request.intent_id,
        ticker=request.ticker,
        side=request.side,
        quantity=request.quantity,
        limit_price=request.limit_price,
        estimated_notional_jpy=request.estimated_notional_jpy,
    )
    send_result: LivePilotSendResult = send_exactly_one_live_pilot(
        send_request,
        nonce=request.nonce,
        expected_account_fingerprint=request.expected_account_fingerprint,
        readiness_report=readiness_payload,
        same_run_preflight=preflight,
        expected_commit_sha=request.expected_commit_sha,
        final_confirmation=request.final_confirmation,
        repository_root=repository_root,
    )

    if send_result.recovery_required:
        return _reconcile_once(
            request,
            send_status=send_result.status,
            order_transport_called=send_result.sent,
        )

    return LivePilotOperationalResult(
        status=send_result.status,
        checked_at=_utc_now().isoformat(timespec="seconds"),
        recovery_only=False,
        preflight_ready=True,
        send_status=send_result.status,
        completion_status=None,
        complete=False,
        blockers=(send_result.message,) if send_result.message else (),
        broker_connection_used=True,
        order_transport_called=send_result.sent,
    )


def persist_operational_result(
    result: LivePilotOperationalResult,
    *,
    report_path: Path = DEFAULT_OPERATIONAL_RESULT,
) -> None:
    _persist_json(
        report_path,
        {
            "schema_version": 1,
            **asdict(result),
            "live_execution_authorized_by_this_report": False,
            "interpretation": (
                "This report records one bounded operational pass. COMPLETE is "
                "evidence of reconciliation only; it never authorizes another send."
            ),
        },
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one fail-closed bounded Live-pilot operational pass."
    )
    parser.add_argument("--intent-id", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--side", required=True)
    parser.add_argument("--quantity", required=True, type=int)
    parser.add_argument("--limit-price", required=True, type=float)
    parser.add_argument("--estimated-notional-jpy", required=True, type=float)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--account-fingerprint", required=True)
    parser.add_argument("--expected-commit-sha", required=True)
    parser.add_argument("--final-confirmation", default="")
    parser.add_argument("--live-readonly-confirmation", required=True)
    parser.add_argument("--repository-root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = LivePilotOperationalRequest(
        intent_id=args.intent_id,
        ticker=args.ticker,
        side=args.side,
        quantity=args.quantity,
        limit_price=args.limit_price,
        estimated_notional_jpy=args.estimated_notional_jpy,
        nonce=args.nonce,
        expected_account_fingerprint=args.account_fingerprint,
        expected_commit_sha=args.expected_commit_sha,
        final_confirmation=args.final_confirmation,
        live_readonly_confirmation=args.live_readonly_confirmation,
    )
    result = run_live_pilot_operational_once(
        request,
        repository_root=Path(args.repository_root),
    )
    persist_operational_result(result)
    print("===== LIVE PILOT OPERATIONAL ONCE =====")
    print("STATUS                 :", result.status)
    print("RECOVERY ONLY          :", result.recovery_only)
    print("PREFLIGHT READY        :", result.preflight_ready)
    print("SEND STATUS            :", result.send_status)
    print("COMPLETION STATUS      :", result.completion_status)
    print("COMPLETE               :", result.complete)
    print("ORDER TRANSPORT CALLED :", result.order_transport_called)
    print("AUTOMATIC RETRY        : False")
    print("AUTOMATIC CANCEL       : False")
    print("AUTOMATIC MODIFY       : False")
    print("AUTOMATIC FLATTEN      : False")
    print("AUTOMATIC CLOSE        : False")
    print("REPORT                 :", DEFAULT_OPERATIONAL_RESULT)
    return 0 if result.complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
