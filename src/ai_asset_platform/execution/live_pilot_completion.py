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

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from ai_asset_platform.brokers.ibkr_live_all_open_orders import (
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_OPEN_ORDERS_REPORT,
)
from ai_asset_platform.brokers.ibkr_live_postfill_evidence import (
    DEFAULT_REPORT_PATH as DEFAULT_POSTFILL_REPORT,
)
from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    DEFAULT_REPORT_PATH as DEFAULT_LIVE_ACCOUNT_REPORT,
)
from ai_asset_platform.execution.live_pilot_send_journal import (
    DEFAULT_JOURNAL_DIR,
    load_send_journal,
)


DEFAULT_PAPER_MONITOR_REPORT = Path("results/ibkr_paper_operations_monitor_latest.json")
DEFAULT_COMPLETION_REPORT = Path("results/live_pilot_completion_latest.json")
DEFAULT_OPERATOR_ALERT = Path("results/live_pilot_completion_alert_latest.json")
REPORT_SCHEMA_VERSION = 2
DEFAULT_MAX_EVIDENCE_AGE_SECONDS = 120.0
_VALID_LIVE_PORTS = {4001, 7496}


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


def _paper_safe(report: dict | None) -> bool:
    if not isinstance(report, dict):
        return False
    broker = report.get("broker")
    broker = broker if isinstance(broker, dict) else {}
    try:
        reconciliation_blockers = int(broker.get("reconciliation_blocker_count", 0) or 0)
        paper_open_orders = int(broker.get("open_order_count", 0) or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        str(report.get("status") or "").strip().upper() != "CRITICAL"
        and report.get("accounting_safe") is True
        and report.get("risk_safe") is True
        and reconciliation_blockers == 0
        and paper_open_orders == 0
        and not report.get("monitor_order_sent")
        and not report.get("live_order_sent")
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
    total = 0.0
    for row in positions:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").strip().upper() != expected_symbol:
            continue
        if str(row.get("sec_type") or "").strip().upper() != "STK":
            continue
        if str(row.get("currency") or "").strip().upper() != expected_currency:
            continue
        quantity = _finite(row.get("quantity"))
        if quantity is None:
            return None
        total += quantity
    return total


def _clean_live_report(report: dict | None) -> bool:
    return bool(
        isinstance(report, dict)
        and report.get("ready") is True
        and report.get("connection_mode") == "LIVE_READ_ONLY"
        and not report.get("order_sent")
        and not report.get("cancel_sent")
        and not report.get("live_order_sent")
    )


def evaluate_live_pilot_completion(
    *,
    intent_id: str,
    ticker: str,
    side: str,
    quantity: int,
    expected_account_fingerprint: str,
    send_journal: dict | None,
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
            send_journal.get("state") == "POSTFILL_PROVEN"
            and str(send_journal.get("intent_id") or "").strip() == intent
            and int(send_journal.get("send_attempt_count", 0) or 0) == 1
            and order_id is not None
            and order_id > 0
            and perm_id is not None
            and perm_id > 0
            and exec_id
            and send_journal.get("recovery_required") is False
            and send_journal.get("automatic_resend_allowed") is False
            and send_journal.get("automatic_cancel_allowed") is False
            and send_journal.get("automatic_modify_allowed") is False
        )
    if not journal_ready:
        blockers.append("durable send journal is not in exact POSTFILL_PROVEN state")

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

    postfill_clean = _clean_live_report(postfill_report)
    account_clean = _clean_live_report(final_account_report)
    open_orders_clean = _clean_live_report(final_open_orders_report)
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
    ):
        observed = (
            str(report.get("account_fingerprint") or "").strip().lower()
            if isinstance(report, dict)
            else ""
        )
        if observed != fingerprint:
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

            total_quantity = 0.0
            gross = 0.0
            currencies: set[str] = set()
            rows_valid = True
            for row in matches:
                row_qty = _positive(row.get("quantity"))
                row_price = _positive(row.get("price"))
                currency = str(row.get("currency") or "").strip().upper()
                if row_qty is None or row_price is None:
                    blockers.append("final Live execution contains invalid quantity or price")
                    rows_valid = False
                    continue
                if len(currency) != 3:
                    blockers.append("final Live execution contains invalid currency")
                    rows_valid = False
                currencies.add(currency)
                total_quantity += row_qty
                gross += row_qty * row_price

            filled_quantity = total_quantity
            if not math.isclose(
                total_quantity,
                float(normalized_quantity),
                rel_tol=1e-12,
                abs_tol=1e-9,
            ):
                blockers.append(
                    f"final Live execution total quantity does not equal pilot quantity: {total_quantity} != {normalized_quantity}"
                )
            if len(currencies) != 1:
                blockers.append("final Live execution rows do not share one currency")
            execution_currency = next(iter(currencies)) if len(currencies) == 1 else None
            if rows_valid and total_quantity > 0:
                execution_price = gross / total_quantity

            commissions = postfill_report.get("commissions")
            commissions = commissions if isinstance(commissions, list) else []
            commission_total = 0.0
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
                parsed_commission = _finite(commission_row.get("commission"))
                observed_currency = str(commission_row.get("currency") or "").strip().upper()
                if parsed_commission is None:
                    blockers.append(f"final commission for exec_id {execution_exec_id} is non-finite")
                    continue
                if execution_currency is None or observed_currency != execution_currency:
                    blockers.append(
                        f"final commission currency for exec_id {execution_exec_id} does not match execution currency"
                    )
                    continue
                commission_total += parsed_commission
                valid_commission_count += 1

            commission_count = valid_commission_count
            if matches and valid_commission_count == len(matches):
                commission = commission_total
                commission_currency = execution_currency

    final_position = _target_position_quantity(final_account_report, normalized_ticker)
    expected_final_position = (
        float(normalized_quantity) if normalized_side == "BUY" else 0.0
    )
    if final_position is None or final_position != expected_final_position:
        blockers.append("final Live position does not equal the exact expected pilot position")

    final_open_order_count: int | None = None
    if isinstance(final_open_orders_report, dict):
        try:
            final_open_order_count = int(final_open_orders_report.get("open_order_count"))
        except (TypeError, ValueError):
            final_open_order_count = None
    if final_open_order_count != 0:
        blockers.append("final Live open-order count is not zero")

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
    return evaluate_live_pilot_completion(
        intent_id=intent_id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        expected_account_fingerprint=expected_account_fingerprint,
        send_journal=journal,
        postfill_report=postfill,
        final_account_report=account,
        final_open_orders_report=open_orders,
        paper_monitor_report=paper,
        now=now,
    )


def persist_live_pilot_completion(
    result: LivePilotCompletion,
    *,
    report_path: Path = DEFAULT_COMPLETION_REPORT,
    alert_path: Path = DEFAULT_OPERATOR_ALERT,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        **asdict(result),
        "interpretation": (
            "COMPLETE means every matching execution and per-exec commission reconciles to the exact "
            "pilot quantity, with final position, zero final Live open orders, matching account/endpoint, "
            "and clean Paper safety evidence."
        ),
    }
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)

    alert = {
        "schema_version": 1,
        "checked_at": result.checked_at,
        "severity": "SUCCESS" if result.complete else "CRITICAL",
        "status": result.status,
        "intent_id": result.intent_id,
        "message": (
            "FIRST LIVE PILOT COMPLETION PROVEN"
            if result.complete
            else "FIRST LIVE PILOT NOT COMPLETE - DO NOT RETRY AUTOMATICALLY"
        ),
        "blockers": list(result.blockers),
        "delivery": "LOCAL_DURABLE_OPERATOR_ALERT",
        "external_notification_claimed": False,
    }
    alert_path.parent.mkdir(parents=True, exist_ok=True)
    alert_tmp = alert_path.with_suffix(alert_path.suffix + ".tmp")
    alert_tmp.write_text(
        json.dumps(alert, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    alert_tmp.replace(alert_path)
