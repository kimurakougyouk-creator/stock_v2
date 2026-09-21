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
import json
import math
from pathlib import Path

from ai_asset_platform.brokers.ibkr_live_all_open_orders import (
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_OPEN_ORDERS_REPORT,
    persist_live_all_open_orders,
    preview_ibkr_live_all_open_orders,
)
from ai_asset_platform.brokers.ibkr_live_fx_evidence import (
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_FX_REPORT,
    persist_live_fx_evidence,
    resolve_ibkr_live_fx_evidence,
)
from ai_asset_platform.brokers.ibkr_live_postfill_evidence import (
    DEFAULT_REPORT_PATH as DEFAULT_POSTFILL_REPORT,
    match_live_postfill,
    persist_live_postfill_snapshot,
    preview_ibkr_live_postfill_snapshot,
)
from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    CONFIRMATION_VALUE as LIVE_READONLY_CONFIRMATION_VALUE,
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_ACCOUNT_REPORT,
    persist_live_readonly_account_snapshot,
    preview_ibkr_live_readonly_account_snapshot,
)
from ai_asset_platform.execution.live_pilot_completion import (
    DEFAULT_COMPLETION_REPORT,
    DEFAULT_OPERATOR_ALERT,
    audit_live_pilot_completion,
    persist_live_pilot_completion,
)
from ai_asset_platform.execution.live_pilot_same_run_preflight import (
    LivePilotSameRunPreflight,
    evaluate_live_pilot_same_run_preflight,
    preflight_record,
)
from ai_asset_platform.execution.live_pilot_send_journal import (
    DEFAULT_JOURNAL_DIR,
    global_send_attempt_recorded,
    load_send_journal,
    mark_postfill_proven,
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


def _collect_presend_readonly_evidence(
    request: LivePilotOperationalRequest,
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
        raise PermissionError("durable sender client_id is missing or invalid")
    if (
        not isinstance(authorized_endpoint_port, int)
        or isinstance(authorized_endpoint_port, bool)
        or authorized_endpoint_port not in {4001, 7496}
    ):
        raise PermissionError("durable authorized Live endpoint is missing or invalid")
    postfill = preview_ibkr_live_postfill_snapshot(
        confirmation=request.live_readonly_confirmation,
        expected_client_id=sender_client_id,
        endpoint_port=authorized_endpoint_port,
    )
    persist_live_postfill_snapshot(postfill)

    account = preview_ibkr_live_readonly_account_snapshot(
        confirmation=request.live_readonly_confirmation
    )
    persist_live_readonly_account_snapshot(account)

    open_orders = preview_ibkr_live_all_open_orders(
        confirmation=request.live_readonly_confirmation
    )
    persist_live_all_open_orders(open_orders)


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
    parsed = float(value)
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


def _reconcile_once(
    request: LivePilotOperationalRequest,
    *,
    send_status: str | None,
    order_transport_called: bool,
) -> LivePilotOperationalResult:
    journal = load_send_journal(request.intent_id, directory=DEFAULT_JOURNAL_DIR)
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

    _collect_post_attempt_readonly_evidence(request)
    _promote_postfill_if_proven(request)

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
        journal = load_send_journal(request.intent_id, directory=DEFAULT_JOURNAL_DIR)
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

    _collect_presend_readonly_evidence(request)
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
