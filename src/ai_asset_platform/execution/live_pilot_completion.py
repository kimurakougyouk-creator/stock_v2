"""Fail-closed completion judge for the first bounded IBKR Live pilot.

This module is post-transport evidence processing only. It connects to no broker
and sends no order. A pilot is COMPLETE only when the durable send journal, all
matching execution+commission proof, final Live account position, final Live
open-order snapshot, and Paper safety monitor all agree while fresh.

One broker order may be split into multiple execution rows. Completion therefore
aggregates every matching execution for the exact orderId/permId and requires one
commission record per unique exec_id. Duplicate, missing, overfilled, underfilled,
or conflicting evidence fails closed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
import fcntl
import json
import math
import os
from pathlib import Path

from ai_asset_platform.brokers.ibkr_live_all_open_orders import (
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_OPEN_ORDERS_REPORT,
    REPORT_SCHEMA_VERSION as _REQUIRED_OPEN_ORDERS_SCHEMA_VERSION,
)
from ai_asset_platform.brokers.ibkr_live_postfill_evidence import (
    DEFAULT_REPORT_PATH as DEFAULT_POSTFILL_REPORT,
    REPORT_SCHEMA_VERSION as _REQUIRED_POSTFILL_SCHEMA_VERSION,
)
from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_ACCOUNT_REPORT,
    REPORT_SCHEMA_VERSION as _REQUIRED_ACCOUNT_SCHEMA_VERSION,
)
from ai_asset_platform.execution.live_pilot_send_journal import (
    DEFAULT_JOURNAL_DIR,
    REPORT_SCHEMA_VERSION as _REQUIRED_SEND_JOURNAL_SCHEMA_VERSION,
    load_global_send_attempt_marker,
    load_send_attempt_marker,
    load_send_journal,
)


DEFAULT_PAPER_MONITOR_REPORT = Path("results/ibkr_paper_operations_monitor_latest.json")
DEFAULT_COMPLETION_REPORT = Path("results/live_pilot_completion_latest.json")
DEFAULT_OPERATOR_ALERT = Path("results/live_pilot_completion_alert_latest.json")
REPORT_SCHEMA_VERSION = 2
DEFAULT_MAX_EVIDENCE_AGE_SECONDS = 120.0
_VALID_LIVE_PORTS = {4001, 7496}
_VALID_PAPER_PORTS = {4002, 7497}
_CLEAN_RECONCILIATION_ACTION = "RECONCILIATION_EVIDENCE_IS_CLEAN"
# ibkr_paper_operations_monitor.py hardcodes "schema_version": 1 inline in
# PaperOperationsMonitorResult.as_record() rather than exporting a constant.
_REQUIRED_PAPER_MONITOR_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LivePilotCompletion:
    status: str
    checked_at: str
    blockers: tuple[str, ...]
    intent_id: str
    ticker: str
    side: str
    quantity: int
    account_fingerprint: str
    order_id: int | None
    perm_id: int | None
    exec_id: str | None
    execution_price: float | None
    commission: float | None
    commission_currency: str | None
    final_position_quantity: float | None
    final_open_order_count: int | None
    endpoint_port: int | None
    evidence_fresh: bool
    paper_monitor_safe: bool
    complete: bool
    broker_connection_used: bool = False
    order_sent: bool = False
    live_order_sent: bool = False
    exec_ids: tuple[str, ...] = ()
    execution_count: int = 0
    filled_quantity: float | None = None
    commission_count: int = 0


def _utc(value: datetime | None) -> datetime:
    current = value if value is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("completion clock must be timezone-aware")
    return current.astimezone(timezone.utc)


def _fresh(report: dict | None, *, now: datetime, max_age_seconds: float) -> bool:
    if not isinstance(report, dict):
        return False
    try:
        observed = datetime.fromisoformat(str(report.get("checked_at") or "").strip())
    except ValueError:
        return False
    if observed.tzinfo is None or observed.utcoffset() is None:
        return False
    age = (now - observed.astimezone(timezone.utc)).total_seconds()
    return 0.0 <= age <= max_age_seconds


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive(value: object) -> float | None:
    parsed = _finite(value)
    return parsed if parsed is not None and parsed > 0 else None


def _decimal(value: object) -> Decimal | None:
    """Parse to an exact, finite ``Decimal`` (never NaN/Infinity).

    ``Decimal`` avoids the binary-float rounding that made
    ``math.isclose(1.0000000005, 1.0)`` accept a real underfill/overfill,
    and lets every intermediate sum/product be checked for finiteness
    (``DecimalException`` such as ``Overflow``) before it can propagate.
    """
    try:
        parsed = Decimal(str(value))
    except (DecimalException, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _positive_decimal(value: object) -> Decimal | None:
    parsed = _decimal(value)
    return parsed if parsed is not None and parsed > 0 else None


def _finite_float_from_decimal(value: Decimal | None) -> float | None:
    if value is None or not value.is_finite():
        return None
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _is_exact_int(value: object, expected: int) -> bool:
    """True only for the exact ``int`` value, not ``1.0``, ``"1"``, or ``True``.

    ``int(value)`` silently coerces all of those (and ``bool`` is itself an
    ``int`` subclass), which would let type-invalid marker/journal counts
    (e.g. a send_attempt_count of ``1.5`` or ``"1"``) pass as exactly one.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _is_exact_zero_int(value: object) -> bool:
    return _is_exact_int(value, 0)


def _paper_safe(report: dict | None) -> bool:
    """Require an exact HEALTHY, schema-current, fully-explicit Paper evidence contract.

    ``ibkr_paper_operations_monitor.py`` reports an unavailable reconciliation
    or open-order snapshot as ``WARNING`` and defaults the corresponding
    counters to zero. Every current ``WARNING``-causing condition happens to
    be covered by the explicit broker-readiness checks below, but requiring
    the aggregate status to be exactly ``HEALTHY`` (not merely not
    ``CRITICAL``) is required so a future warning condition not yet mirrored
    by a specific field check still fails closed instead of silently
    passing. The report's own schema version is checked so schema drift
    cannot be reconciled by field-name coincidence, and every transport flag
    must be the exact boolean ``False`` rather than merely falsy (``None``,
    ``0``, missing) evidence.
    """
    if not isinstance(report, dict):
        return False
    if report.get("schema_version") != _REQUIRED_PAPER_MONITOR_SCHEMA_VERSION:
        return False
    broker = report.get("broker")
    broker = broker if isinstance(broker, dict) else {}
    if not (
        _is_exact_zero_int(broker.get("reconciliation_blocker_count"))
        and _is_exact_zero_int(broker.get("open_order_count"))
    ):
        return False
    open_orders = broker.get("open_orders")
    if not isinstance(open_orders, list) or len(open_orders) != 0:
        # The Paper monitor's schema always emits this list; an exact-zero
        # count alone must not be trusted if the accompanying rows are
        # missing, malformed, or (contradictorily) nonempty.
        return False
    try:
        endpoint_port = int(broker.get("endpoint_port"))
    except (TypeError, ValueError):
        return False
    return bool(
        report.get("status") == "HEALTHY"
        and report.get("accounting_safe") is True
        and report.get("risk_safe") is True
        and broker.get("account_ready") is True
        and broker.get("execution_snapshot_ready") is True
        and broker.get("all_open_orders_ready") is True
        and str(broker.get("reconciliation_next_action") or "").strip()
        == _CLEAN_RECONCILIATION_ACTION
        and endpoint_port in _VALID_PAPER_PORTS
        and report.get("monitor_order_sent") is False
        and report.get("live_order_sent") is False
    )


def _target_position_quantity(account_report: dict | None, ticker: str) -> float | None:
    if not isinstance(account_report, dict):
        return None
    positions = account_report.get("positions")
    if not isinstance(positions, list):
        return None
    normalized = str(ticker or "").strip().upper()
    expected_symbol = "9432" if normalized == "9432.T" else normalized
    expected_currency = "JPY" if normalized == "9432.T" else "USD"
    total = Decimal("0")
    for row in positions:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").strip().upper() != expected_symbol:
            continue
        if str(row.get("sec_type") or "").strip().upper() != "STK":
            continue
        if str(row.get("currency") or "").strip().upper() != expected_currency:
            continue
        quantity = _decimal(row.get("quantity"))
        if quantity is None:
            return None
        try:
            total += quantity
        except DecimalException:
            return None
        if not total.is_finite():
            return None
    return _finite_float_from_decimal(total)


def _execution_identity(row: dict) -> tuple:
    def _lenient_int(value: object) -> object:
        try:
            return int(value)
        except (TypeError, ValueError):
            return str(value)

    return (
        _lenient_int(row.get("order_id")),
        _lenient_int(row.get("perm_id")),
        str(row.get("symbol") or "").strip().upper(),
        str(row.get("sec_type") or "").strip().upper(),
        str(row.get("side") or "").strip().upper(),
        str(row.get("account_fingerprint") or "").strip().lower(),
    )


def _clean_live_report(
    report: dict | None,
    *,
    required_schema_version: int,
    required_false_flags: tuple[str, ...],
) -> bool:
    """Require exact schema/readiness and exact-``False`` transport flags.

    Every flag a given report type's own producer schema defines is required
    to be the exact boolean ``False`` rather than merely falsy (``None``,
    ``0``, missing). ``cancel_sent`` is additionally rejected if *present at
    all*, even on report types (postfill/account) that never define it in
    their own schema: an otherwise valid, schema-versioned report that
    nonetheless carries an explicit ``cancel_sent: true`` must not be
    silently ignored just because that report type's contract doesn't
    officially require the field.
    """
    if not isinstance(report, dict):
        return False
    if report.get("schema_version") != required_schema_version:
        return False
    if report.get("ready") is not True or report.get("connection_mode") != "LIVE_READ_ONLY":
        return False
    if not all(report.get(flag) is False for flag in required_false_flags):
        return False
    if "cancel_sent" in report and report.get("cancel_sent") is not False:
        return False
    return True


def evaluate_live_pilot_completion(
    *,
    intent_id: str,
    ticker: str,
    side: str,
    quantity: int,
    expected_account_fingerprint: str,
    send_journal: dict | None,
    send_attempt_marker: dict | None,
    global_send_attempt_marker: dict | None,
    postfill_report: dict | None,
    final_account_report: dict | None,
    final_open_orders_report: dict | None,
    paper_monitor_report: dict | None,
    now: datetime | None = None,
    max_evidence_age_seconds: float = DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
) -> LivePilotCompletion:
    current = _utc(now)
    try:
        max_age = float(max_evidence_age_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_evidence_age_seconds must be positive and finite") from exc
    if not math.isfinite(max_age) or max_age <= 0:
        raise ValueError("max_evidence_age_seconds must be positive and finite")

    intent = str(intent_id or "").strip()
    normalized_ticker = str(ticker or "").strip().upper()
    normalized_side = str(side or "").strip().upper()
    fingerprint = str(expected_account_fingerprint or "").strip().lower()
    try:
        normalized_quantity = int(quantity)
    except (TypeError, ValueError):
        normalized_quantity = 0
    blockers: list[str] = []

    if not intent:
        blockers.append("intent_id is missing")
    if normalized_side not in {"BUY", "SELL"}:
        blockers.append("side must be BUY or SELL")
    if normalized_quantity <= 0:
        blockers.append("quantity must be positive")
    if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
        blockers.append("expected account fingerprint is invalid")

    order_id: int | None = None
    perm_id: int | None = None
    exec_id: str | None = None
    journal_ready = False
    if isinstance(send_journal, dict):
        try:
            order_id = int(send_journal.get("order_id"))
            perm_id = int(send_journal.get("perm_id"))
        except (TypeError, ValueError):
            order_id = perm_id = None
        exec_id = str(send_journal.get("exec_id") or "").strip() or None
        journal_ready = bool(
            send_journal.get("schema_version") == _REQUIRED_SEND_JOURNAL_SCHEMA_VERSION
            and send_journal.get("state") == "POSTFILL_PROVEN"
            and str(send_journal.get("intent_id") or "").strip() == intent
            and _is_exact_int(send_journal.get("send_attempt_count"), 1)
            and order_id is not None
            and order_id > 0
            and perm_id is not None
            and perm_id > 0
            and exec_id
            and send_journal.get("recovery_required") is False
            and send_journal.get("automatic_resend_allowed") is False
            and send_journal.get("automatic_cancel_allowed") is False
            and send_journal.get("automatic_modify_allowed") is False
            and send_journal.get("automatic_flatten_allowed") is False
            and send_journal.get("automatic_close_allowed") is False
        )
    if not journal_ready:
        blockers.append("durable send journal is not in exact POSTFILL_PROVEN state")

    marker_nonce = (
        str(send_attempt_marker.get("nonce") or "").strip()
        if isinstance(send_attempt_marker, dict)
        else ""
    )
    journal_nonce = (
        str(send_journal.get("nonce") or "").strip()
        if isinstance(send_journal, dict)
        else ""
    )
    marker_ready = bool(
        isinstance(send_attempt_marker, dict)
        and send_attempt_marker.get("schema_version") == _REQUIRED_SEND_JOURNAL_SCHEMA_VERSION
        and send_attempt_marker.get("state") == "SEND_ATTEMPT_RECORDED"
        and str(send_attempt_marker.get("intent_id") or "").strip() == intent
        and isinstance(send_journal, dict)
        and marker_nonce
        and marker_nonce == journal_nonce
        and send_attempt_marker.get("automatic_resend_allowed") is False
        and send_attempt_marker.get("automatic_cancel_allowed") is False
        and send_attempt_marker.get("automatic_modify_allowed") is False
        and send_attempt_marker.get("automatic_flatten_allowed") is False
        and send_attempt_marker.get("automatic_close_allowed") is False
    )
    if not marker_ready:
        blockers.append(
            "irreversible send-attempt marker is missing, mismatched, or inconsistent"
        )

    global_marker_ready = bool(
        isinstance(global_send_attempt_marker, dict)
        and global_send_attempt_marker.get("schema_version")
        == _REQUIRED_SEND_JOURNAL_SCHEMA_VERSION
        and str(global_send_attempt_marker.get("intent_id") or "").strip() == intent
        and global_send_attempt_marker.get("automatic_resend_allowed") is False
    )
    if not global_marker_ready:
        blockers.append(
            "campaign-wide global send-attempt marker is missing, bound to a "
            "different intent, or inconsistent"
        )

    postfill_fresh = _fresh(postfill_report, now=current, max_age_seconds=max_age)
    account_fresh = _fresh(final_account_report, now=current, max_age_seconds=max_age)
    open_orders_fresh = _fresh(final_open_orders_report, now=current, max_age_seconds=max_age)
    paper_fresh = _fresh(paper_monitor_report, now=current, max_age_seconds=max_age)
    evidence_fresh = all((postfill_fresh, account_fresh, open_orders_fresh, paper_fresh))
    if not postfill_fresh:
        blockers.append("Live post-fill evidence is missing or stale")
    if not account_fresh:
        blockers.append("final Live account evidence is missing or stale")
    if not open_orders_fresh:
        blockers.append("final Live open-order evidence is missing or stale")
    if not paper_fresh:
        blockers.append("Paper monitor evidence is missing or stale")

    postfill_clean = _clean_live_report(
        postfill_report,
        required_schema_version=_REQUIRED_POSTFILL_SCHEMA_VERSION,
        required_false_flags=("order_sent", "live_order_sent"),
    )
    account_clean = _clean_live_report(
        final_account_report,
        required_schema_version=_REQUIRED_ACCOUNT_SCHEMA_VERSION,
        required_false_flags=("order_sent", "live_order_sent"),
    )
    open_orders_clean = _clean_live_report(
        final_open_orders_report,
        required_schema_version=_REQUIRED_OPEN_ORDERS_SCHEMA_VERSION,
        required_false_flags=("order_sent", "cancel_sent", "live_order_sent"),
    )
    if not postfill_clean:
        blockers.append("Live post-fill report is not clean read-only evidence")
    if not account_clean:
        blockers.append("final Live account report is not clean read-only evidence")
    if not open_orders_clean:
        blockers.append("final Live open-order report is not clean read-only evidence")

    reports = [postfill_report, final_account_report, final_open_orders_report]
    ports: list[int] = []
    for report in reports:
        try:
            port = int(report.get("endpoint_port")) if isinstance(report, dict) else 0
        except (TypeError, ValueError):
            port = 0
        if port in _VALID_LIVE_PORTS:
            ports.append(port)
        else:
            blockers.append("final Live evidence contains a non-Live or missing endpoint")
    endpoint_port = ports[0] if len(ports) == 3 and len(set(ports)) == 1 else None
    if endpoint_port is None:
        blockers.append("final Live evidence is not bound to one Live endpoint")

    for label, report in (
        ("post-fill", postfill_report),
        ("account", final_account_report),
        ("open-orders", final_open_orders_report),
    ):
        observed = (
            str(report.get("account_fingerprint") or "").strip().lower()
            if isinstance(report, dict)
            else ""
        )
        if not observed or observed != fingerprint:
            blockers.append(f"final Live {label} account fingerprint mismatch")

    execution_price: float | None = None
    commission: float | None = None
    commission_currency: str | None = None
    exec_ids: tuple[str, ...] = ()
    execution_count = 0
    filled_quantity: float | None = None
    commission_count = 0

    if journal_ready and isinstance(postfill_report, dict):
        expected_symbol = "9432" if normalized_ticker == "9432.T" else normalized_ticker
        executions = postfill_report.get("executions")
        executions = executions if isinstance(executions, list) else []
        matches: list[dict] = []
        expected_identity = (
            order_id,
            perm_id,
            expected_symbol,
            "STK",
            normalized_side,
            fingerprint,
        )
        for row in executions:
            if not isinstance(row, dict):
                continue
            try:
                row_order = int(row.get("order_id"))
                row_perm = int(row.get("perm_id"))
            except (TypeError, ValueError):
                continue
            if (
                row_order == order_id
                and row_perm == perm_id
                and _execution_identity(row) != expected_identity
            ):
                blockers.append(
                    "final Live execution carrying the reconciled order identity "
                    "conflicts with the expected execution identity"
                )
            if (
                row_order == order_id
                and row_perm == perm_id
                and str(row.get("symbol") or "").strip().upper() == expected_symbol
                and str(row.get("sec_type") or "").strip().upper() == "STK"
                and str(row.get("side") or "").strip().upper() == normalized_side
                and str(row.get("account_fingerprint") or "").strip().lower() == fingerprint
            ):
                matches.append(row)

        execution_count = len(matches)
        if not matches:
            blockers.append("no matching final Live execution rows were found")
        else:
            ids = [str(row.get("exec_id") or "").strip() for row in matches]
            exec_ids = tuple(ids)
            if any(not value for value in ids) or len(ids) != len(set(ids)):
                blockers.append("final Live executions contain missing or duplicate exec_id evidence")
            if exec_id not in ids:
                blockers.append("durable journal exec_id is not present in final Live execution evidence")

            # A conflicting row can share an exec_id with a matched row while
            # disagreeing on order/perm/account/symbol/side identity; such a
            # row is deliberately retained (not deduplicated) by the postfill
            # collector so it fails closed here instead of being silently
            # dropped by the order/perm/account/symbol/side filter above.
            for target_exec_id in set(ids):
                if not target_exec_id:
                    continue
                identities = {
                    _execution_identity(row)
                    for row in executions
                    if isinstance(row, dict)
                    and str(row.get("exec_id") or "").strip() == target_exec_id
                }
                if len(identities) > 1:
                    blockers.append(
                        f"exec_id {target_exec_id} appears with conflicting execution identity evidence"
                    )

            expected_instrument_currency = "JPY" if normalized_ticker == "9432.T" else "USD"
            total_quantity = Decimal("0")
            gross = Decimal("0")
            currencies: set[str] = set()
            rows_valid = True
            for row in matches:
                row_qty = _positive_decimal(row.get("quantity"))
                row_price = _positive_decimal(row.get("price"))
                currency = str(row.get("currency") or "").strip().upper()
                if row_qty is None or row_price is None:
                    blockers.append("final Live execution contains invalid quantity or price")
                    rows_valid = False
                    continue
                if len(currency) != 3:
                    blockers.append("final Live execution contains invalid currency")
                    rows_valid = False
                elif currency != expected_instrument_currency:
                    blockers.append(
                        f"final Live execution currency {currency} does not match the "
                        f"expected instrument currency {expected_instrument_currency}"
                    )
                    rows_valid = False
                currencies.add(currency)
                try:
                    product = row_qty * row_price
                    if not product.is_finite():
                        raise DecimalException
                    total_quantity += row_qty
                    gross += product
                    if not total_quantity.is_finite() or not gross.is_finite():
                        raise DecimalException
                except DecimalException:
                    blockers.append("final Live execution aggregate is non-finite")
                    rows_valid = False

            filled_quantity = _finite_float_from_decimal(total_quantity)
            if total_quantity != Decimal(normalized_quantity):
                blockers.append(
                    f"final Live execution total quantity does not equal pilot quantity: {total_quantity} != {normalized_quantity}"
                )
            if len(currencies) != 1:
                blockers.append("final Live execution rows do not share one currency")
            execution_currency = next(iter(currencies)) if len(currencies) == 1 else None
            if rows_valid and total_quantity > 0:
                try:
                    execution_price = _finite_float_from_decimal(gross / total_quantity)
                except DecimalException:
                    execution_price = None
                if execution_price is None:
                    blockers.append("final Live execution VWAP is non-finite")

            commissions = postfill_report.get("commissions")
            commissions = commissions if isinstance(commissions, list) else []
            commission_total = Decimal("0")
            valid_commission_count = 0
            for execution_row in matches:
                execution_exec_id = str(execution_row.get("exec_id") or "").strip()
                commission_matches = [
                    row
                    for row in commissions
                    if isinstance(row, dict)
                    and str(row.get("exec_id") or "").strip() == execution_exec_id
                ]
                if len(commission_matches) != 1:
                    blockers.append(
                        f"expected exactly one final commission for exec_id {execution_exec_id}; found {len(commission_matches)}"
                    )
                    continue
                commission_row = commission_matches[0]
                parsed_commission = _decimal(commission_row.get("commission"))
                observed_currency = str(commission_row.get("currency") or "").strip().upper()
                if parsed_commission is None:
                    blockers.append(f"final commission for exec_id {execution_exec_id} is non-finite")
                    continue
                if execution_currency is None or observed_currency != execution_currency:
                    blockers.append(
                        f"final commission currency for exec_id {execution_exec_id} does not match execution currency"
                    )
                    continue
                try:
                    commission_total += parsed_commission
                    if not commission_total.is_finite():
                        raise DecimalException
                except DecimalException:
                    blockers.append(f"final commission aggregate is non-finite at exec_id {execution_exec_id}")
                    continue
                valid_commission_count += 1

            commission_count = valid_commission_count
            if matches and valid_commission_count == len(matches):
                commission = _finite_float_from_decimal(commission_total)
                commission_currency = execution_currency
                if commission is None:
                    blockers.append("final commission aggregate cannot be represented finitely")

    final_position = _target_position_quantity(final_account_report, normalized_ticker)
    expected_final_position = (
        float(normalized_quantity) if normalized_side == "BUY" else 0.0
    )
    if final_position is None or final_position != expected_final_position:
        blockers.append("final Live position does not equal the exact expected pilot position")

    final_open_order_count: int | None = None
    final_orders_rows: object = None
    if isinstance(final_open_orders_report, dict):
        raw_count = final_open_orders_report.get("open_order_count")
        if isinstance(raw_count, int) and not isinstance(raw_count, bool):
            final_open_order_count = raw_count
        final_orders_rows = final_open_orders_report.get("orders")
    if final_open_order_count != 0:
        blockers.append("final Live open-order count is not zero")
    if not isinstance(final_orders_rows, list) or len(final_orders_rows) != 0:
        blockers.append("final Live open-order rows are missing, malformed, or not empty")

    paper_safe = _paper_safe(paper_monitor_report)
    if not paper_safe:
        blockers.append("Paper operations monitor is not safe after the Live pilot")

    complete = not blockers
    return LivePilotCompletion(
        status="COMPLETE" if complete else "BLOCKED",
        checked_at=current.isoformat(timespec="seconds"),
        blockers=tuple(blockers),
        intent_id=intent,
        ticker=normalized_ticker,
        side=normalized_side,
        quantity=normalized_quantity,
        account_fingerprint=fingerprint,
        order_id=order_id,
        perm_id=perm_id,
        exec_id=exec_id,
        execution_price=execution_price,
        commission=commission,
        commission_currency=commission_currency,
        final_position_quantity=final_position,
        final_open_order_count=final_open_order_count,
        endpoint_port=endpoint_port,
        evidence_fresh=evidence_fresh,
        paper_monitor_safe=paper_safe,
        complete=complete,
        exec_ids=exec_ids,
        execution_count=execution_count,
        filled_quantity=filled_quantity,
        commission_count=commission_count,
    )


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_full(descriptor: int, data: bytes) -> None:
    """Write every byte of ``data``, since ``os.write`` may write fewer.

    POSIX permits a short write (e.g. an interrupted syscall); persisting
    without looping could fsync and rename a truncated payload as if it were
    complete and valid.
    """
    written = 0
    while written < len(data):
        count = os.write(descriptor, data[written:])
        if count <= 0:
            raise OSError("write() made no progress while persisting durable evidence")
        written += count


def _fsync_parent_dir(path: Path) -> None:
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _mkdir_durable(directory: Path) -> None:
    """Create ``directory`` and any missing parents, durably.

    ``Path.mkdir(parents=True)`` alone does not guarantee the new directory
    entries survive a crash immediately after this call returns; each newly
    created directory's own parent must be fsynced too.
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


def _durable_write_json(path: Path, payload: dict) -> None:
    """Write JSON via fsync'd temp-file-then-rename, then fsync the directory.

    A rename alone is atomic but not necessarily durable: without fsyncing
    the temp file's contents before the rename and the containing directory
    afterward, a crash can lose the file's content or the rename itself even
    though the call already returned, letting two durable artifacts written
    in this order (e.g. an invalidated alert, then a report) end up
    inconsistently ordered after a crash.
    """
    _mkdir_durable(path.parent)
    temporary = path.with_suffix(path.suffix + ".tmp")
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        _write_full(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_parent_dir(path)

@contextmanager
def _completion_publication_lock(*, report_path: Path, alert_path: Path):
    """Serialize publication for every directory containing either artifact."""
    descriptors: list[int] = []
    directories = sorted(
        {report_path.parent.resolve(), alert_path.parent.resolve()}, key=str
    )
    try:
        for directory in directories:
            _mkdir_durable(directory)
            descriptor = os.open(
                directory / ".live_pilot_completion.lock",
                os.O_RDWR | os.O_CREAT,
                0o600,
            )
            descriptors.append(descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        for descriptor in reversed(descriptors):
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def audit_live_pilot_completion(
    *,
    intent_id: str,
    ticker: str,
    side: str,
    quantity: int,
    expected_account_fingerprint: str,
    journal_dir: Path = DEFAULT_JOURNAL_DIR,
    postfill_report_path: Path = DEFAULT_POSTFILL_REPORT,
    live_account_report_path: Path = DEFAULT_LIVE_ACCOUNT_REPORT,
    live_open_orders_report_path: Path = DEFAULT_LIVE_OPEN_ORDERS_REPORT,
    paper_monitor_report_path: Path = DEFAULT_PAPER_MONITOR_REPORT,
    now: datetime | None = None,
) -> LivePilotCompletion:
    try:
        journal = load_send_journal(intent_id, directory=journal_dir)
        attempt_marker = load_send_attempt_marker(intent_id, directory=journal_dir)
        global_attempt_marker = load_global_send_attempt_marker(directory=journal_dir)
        postfill = _load(postfill_report_path)
        account = _load(live_account_report_path)
        open_orders = _load(live_open_orders_report_path)
        paper = _load(paper_monitor_report_path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        current = _utc(now)
        return LivePilotCompletion(
            status="BLOCKED",
            checked_at=current.isoformat(timespec="seconds"),
            blockers=(f"completion evidence is unreadable: {exc}",),
            intent_id=str(intent_id or "").strip(),
            ticker=str(ticker or "").strip().upper(),
            side=str(side or "").strip().upper(),
            quantity=int(quantity),
            account_fingerprint=str(expected_account_fingerprint or "").strip().lower(),
            order_id=None,
            perm_id=None,
            exec_id=None,
            execution_price=None,
            commission=None,
            commission_currency=None,
            final_position_quantity=None,
            final_open_order_count=None,
            endpoint_port=None,
            evidence_fresh=False,
            paper_monitor_safe=False,
            complete=False,
        )
    try:
        return evaluate_live_pilot_completion(
            intent_id=intent_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            expected_account_fingerprint=expected_account_fingerprint,
            send_journal=journal,
            send_attempt_marker=attempt_marker,
            global_send_attempt_marker=global_attempt_marker,
            postfill_report=postfill,
            final_account_report=account,
            final_open_orders_report=open_orders,
            paper_monitor_report=paper,
            now=now,
        )
    except (DecimalException, ArithmeticError, TypeError, ValueError) as exc:
        # A malformed numeric value (e.g. an extreme exponent that overflows
        # during arithmetic) must still produce and persist a fail-closed
        # BLOCKED result, not abort the audit and risk leaving an older
        # SUCCESS artifact as the last thing anyone persisted.
        current = _utc(now)
        return LivePilotCompletion(
            status="BLOCKED",
            checked_at=current.isoformat(timespec="seconds"),
            blockers=(f"completion evaluation raised on malformed evidence: {exc}",),
            intent_id=str(intent_id or "").strip(),
            ticker=str(ticker or "").strip().upper(),
            side=str(side or "").strip().upper(),
            quantity=int(quantity),
            account_fingerprint=str(expected_account_fingerprint or "").strip().lower(),
            order_id=None,
            perm_id=None,
            exec_id=None,
            execution_price=None,
            commission=None,
            commission_currency=None,
            final_position_quantity=None,
            final_open_order_count=None,
            endpoint_port=None,
            evidence_fresh=False,
            paper_monitor_safe=False,
            complete=False,
        )


def persist_live_pilot_completion(
    result: LivePilotCompletion,
    *,
    report_path: Path = DEFAULT_COMPLETION_REPORT,
    alert_path: Path = DEFAULT_OPERATOR_ALERT,
) -> None:
    """Persist the completion report and its durable operator alert.

    A durable ``SUCCESS`` alert must never exist without a matching, durably
    persisted ``COMPLETE`` report next to it -- an operator or downstream
    consumer may act on the alert alone. This is enforced in three phases:

    1. Write a non-SUCCESS alert first, unconditionally. This invalidates any
       stale ``SUCCESS`` alert left by a prior run before anything else is
       attempted, so a failure in a later phase never leaves a stale success
       claim on disk.
    2. Persist the completion report.
    3. Only if the report was persisted *and* this result is complete,
       promote the alert to ``SUCCESS``. If step 2 raises, this phase never
       runs and the alert remains the non-SUCCESS one from step 1.
    """

    def _write_alert(payload: dict) -> None:
        _durable_write_json(alert_path, payload)

    with _completion_publication_lock(
        report_path=report_path, alert_path=alert_path
    ):
        base_alert = {
            "schema_version": 1,
            "checked_at": result.checked_at,
            "status": result.status,
            "intent_id": result.intent_id,
            "blockers": list(result.blockers),
            "delivery": "LOCAL_DURABLE_OPERATOR_ALERT",
            "external_notification_claimed": False,
        }
        _write_alert(
            {
                **base_alert,
                "status": (
                    "PENDING_REPORT_PERSISTENCE" if result.complete else result.status
                ),
                "severity": "CRITICAL",
                "message": (
                    "FIRST LIVE PILOT COMPLETION PENDING REPORT PERSISTENCE"
                    if result.complete
                    else "FIRST LIVE PILOT NOT COMPLETE - DO NOT RETRY AUTOMATICALLY"
                ),
            }
        )

        payload = {
            "schema_version": REPORT_SCHEMA_VERSION,
            **asdict(result),
            "interpretation": (
                "COMPLETE means every matching execution and per-exec commission reconciles to the exact "
                "pilot quantity, with final position, zero final Live open orders, matching account/endpoint, "
                "and clean Paper safety evidence."
            ),
        }
        _durable_write_json(report_path, payload)

        if result.complete:
            _write_alert(
                {
                    **base_alert,
                    "severity": "SUCCESS",
                    "message": "FIRST LIVE PILOT COMPLETION PROVEN",
                }
            )
