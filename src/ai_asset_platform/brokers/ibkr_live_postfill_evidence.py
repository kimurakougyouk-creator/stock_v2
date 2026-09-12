"""Read-only post-fill evidence for one future IBKR Live pilot.

The collector uses one Live socket to identify the managed account, request
execution history, and receive matching commissionReport callbacks. Raw account
IDs are used only in memory and are never persisted. No order API exists here.

A single order may produce multiple execution rows. Evidence is therefore kept
per ``exec_id`` and must reconcile all matching executions and one commission
record per execution before a fill is considered proven.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from threading import Event, Thread
import time

from ibapi.client import EClient
from ibapi.execution import ExecutionFilter
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    CONFIRMATION_ENV,
    CONFIRMATION_VALUE,
    LIVE_GATEWAY_PORT,
    LIVE_TWS_PORT,
    _account_fingerprint,
)
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely

DEFAULT_REPORT_PATH = Path("results/ibkr_live_postfill_evidence_latest.json")
REPORT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class LiveExecutionEvidence:
    exec_id: str
    order_id: int
    perm_id: int
    symbol: str
    sec_type: str
    currency: str
    side: str
    quantity: float
    price: float
    time: str
    account_fingerprint: str


@dataclass(frozen=True)
class LiveCommissionEvidence:
    exec_id: str
    commission: float
    currency: str
    realized_pnl: float | None


@dataclass(frozen=True)
class IbkrLivePostFillSnapshot:
    attempted: bool
    connected: bool
    endpoint_port: int | None
    account_fingerprint: str | None
    executions: tuple[LiveExecutionEvidence, ...] = ()
    commissions: tuple[LiveCommissionEvidence, ...] = ()
    blocked_reason: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    order_sent: bool = False
    live_order_sent: bool = False

    @property
    def ready(self) -> bool:
        return bool(
            self.attempted
            and self.connected
            and self.endpoint_port in {LIVE_GATEWAY_PORT, LIVE_TWS_PORT}
            and self.account_fingerprint
            and self.blocked_reason is None
            and not self.order_sent
            and not self.live_order_sent
        )


@dataclass(frozen=True)
class LivePostFillMatch:
    ready: bool
    blockers: tuple[str, ...]
    execution: LiveExecutionEvidence | None
    commission: LiveCommissionEvidence | None
    native_cash_effect: float | None
    executions: tuple[LiveExecutionEvidence, ...] = ()
    commissions: tuple[LiveCommissionEvidence, ...] = ()
    filled_quantity: float | None = None
    vwap_price: float | None = None
    commission_total: float | None = None


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive(value: object) -> float | None:
    parsed = _finite(value)
    return parsed if parsed is not None and parsed > 0 else None


class _LivePostFillProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.accounts_ready = Event()
        self.executions_ready = Event()
        self.accounts: list[str] = []
        self.raw_executions: list[tuple[object, object]] = []
        self.commissions: list[LiveCommissionEvidence] = []
        self.errors: list[str] = []
        self.fatal = False

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [x.strip() for x in str(accountsList).split(",") if x.strip()]
        self.accounts_ready.set()

    def execDetails(self, reqId, contract, execution) -> None:  # noqa: N802
        self.raw_executions.append((contract, execution))

    def execDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.executions_ready.set()

    def commissionReport(self, report) -> None:  # noqa: N802
        exec_id = str(getattr(report, "execId", "") or "").strip()
        commission = _finite(getattr(report, "commission", None))
        currency = str(getattr(report, "currency", "") or "").strip().upper()
        if not exec_id or commission is None or len(currency) != 3:
            return
        self.commissions.append(
            LiveCommissionEvidence(
                exec_id=exec_id,
                commission=commission,
                currency=currency,
                realized_pnl=_finite(getattr(report, "realizedPNL", None)),
            )
        )

    def error(self, reqId, *args):
        if len(args) >= 2:
            try:
                code = int(args[-2])
                text = str(args[-1])
            except (TypeError, ValueError):
                return
            self.errors.append(f"{code}: {text}")
            if code in {326, 502, 503, 504, 1100}:
                self.fatal = True
                self.connected_ready.set()
                self.accounts_ready.set()
                self.executions_ready.set()


def _execution_row(contract, execution, account_id: str) -> LiveExecutionEvidence | None:
    if str(getattr(execution, "acctNumber", "") or "").strip() != account_id:
        return None
    raw_side = str(getattr(execution, "side", "") or "").strip().upper()
    side = {"BOT": "BUY", "SLD": "SELL"}.get(raw_side, raw_side)
    try:
        quantity = float(getattr(execution, "shares", 0) or 0)
        price = float(getattr(execution, "price", 0) or 0)
        order_id = int(getattr(execution, "orderId", 0) or 0)
        perm_id = int(getattr(execution, "permId", 0) or 0)
    except (TypeError, ValueError):
        return None
    exec_id = str(getattr(execution, "execId", "") or "").strip()
    if (
        not exec_id
        or not math.isfinite(quantity)
        or not math.isfinite(price)
        or quantity <= 0
        or price <= 0
        or side not in {"BUY", "SELL"}
    ):
        return None
    return LiveExecutionEvidence(
        exec_id=exec_id,
        order_id=order_id,
        perm_id=perm_id,
        symbol=str(getattr(contract, "symbol", "") or "").strip().upper(),
        sec_type=str(getattr(contract, "secType", "") or "").strip().upper(),
        currency=str(getattr(contract, "currency", "") or "").strip().upper(),
        side=side,
        quantity=quantity,
        price=price,
        time=str(getattr(execution, "time", "") or "").strip(),
        account_fingerprint=_account_fingerprint(account_id),
    )


def preview_ibkr_live_postfill_snapshot(
    *, timeout: float = 10.0, settle_seconds: float = 0.25, confirmation: str | None = None,
) -> IbkrLivePostFillSnapshot:
    supplied = str(confirmation).strip() if confirmation is not None else os.getenv(CONFIRMATION_ENV, "").strip()
    if supplied != CONFIRMATION_VALUE:
        return IbkrLivePostFillSnapshot(False, False, None, None, blocked_reason="exact Live read-only confirmation is missing")
    if timeout <= 0 or settle_seconds < 0 or settle_seconds > 2:
        raise ValueError("invalid timeout or settle_seconds")

    errors: list[str] = []
    for index, port in enumerate((LIVE_GATEWAY_PORT, LIVE_TWS_PORT), start=1):
        probe = _LivePostFillProbe()
        try:
            try:
                probe.connect("127.0.0.1", port, 670 + index)
            except OSError as exc:
                errors.append(f"{port}: {exc}")
                continue
            Thread(target=run_ibapi_message_loop_safely, kwargs={"client": probe, "errors": probe.errors}, daemon=True).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal:
                errors.extend(probe.errors)
                continue
            probe.reqManagedAccts()
            if not probe.accounts_ready.wait(timeout) or len(probe.accounts) != 1:
                errors.extend(probe.errors)
                errors.append(f"{port}: expected exactly one managed Live account")
                continue
            account_id = probe.accounts[0]
            probe.reqExecutions(1997, ExecutionFilter())
            if not probe.executions_ready.wait(timeout) or probe.fatal:
                errors.extend(probe.errors)
                continue
            if settle_seconds:
                time.sleep(settle_seconds)
            rows = [
                row
                for contract, execution in probe.raw_executions
                if (row := _execution_row(contract, execution, account_id)) is not None
            ]
            # Keep every row. Duplicate/conflicting exec_id or commission evidence
            # must remain visible so reconciliation can fail closed rather than
            # silently overwriting one broker callback with another.
            return IbkrLivePostFillSnapshot(
                attempted=True,
                connected=True,
                endpoint_port=port,
                account_fingerprint=_account_fingerprint(account_id),
                executions=tuple(rows),
                commissions=tuple(probe.commissions),
                errors=tuple(errors + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()
    return IbkrLivePostFillSnapshot(True, False, None, None, blocked_reason="no Live endpoint produced complete post-fill evidence", errors=tuple(errors))


def match_live_postfill(
    snapshot: IbkrLivePostFillSnapshot,
    *, expected_account_fingerprint: str, ticker: str, side: str, quantity: int,
    order_id: int, perm_id: int,
) -> LivePostFillMatch:
    blockers: list[str] = []
    if not snapshot.ready:
        blockers.append("Live post-fill snapshot is not ready")
    expected_fp = str(expected_account_fingerprint or "").strip().lower()
    if snapshot.account_fingerprint != expected_fp:
        blockers.append("Live account fingerprint mismatch")

    symbol = "9432" if str(ticker).strip().upper() == "9432.T" else str(ticker).strip().upper()
    normalized_side = str(side).strip().upper()
    expected_quantity = _positive(quantity)
    if normalized_side not in {"BUY", "SELL"}:
        blockers.append("side must be BUY or SELL")
    if expected_quantity is None:
        blockers.append("quantity must be positive and finite")

    matches = [
        row
        for row in snapshot.executions
        if row.symbol == symbol
        and row.sec_type == "STK"
        and row.side == normalized_side
        and row.order_id == int(order_id)
        and row.perm_id == int(perm_id)
        and row.account_fingerprint == expected_fp
    ]
    if not matches:
        blockers.append("no matching Live execution rows were found")
        return LivePostFillMatch(False, tuple(blockers), None, None, None)

    exec_ids = [str(row.exec_id or "").strip() for row in matches]
    if any(not value for value in exec_ids) or len(exec_ids) != len(set(exec_ids)):
        blockers.append("matching Live executions contain missing or duplicate exec_id evidence")

    # A conflicting row sharing an exec_id but belonging to a different
    # order/account/symbol/side is filtered out of `matches` above and would
    # otherwise be invisible to the duplicate check. Verify each matched
    # exec_id's occurrence count is unchanged across the full, unfiltered
    # execution set.
    for target_id in {value for value in exec_ids if value}:
        matched_occurrences = exec_ids.count(target_id)
        total_occurrences = sum(
            1 for row in snapshot.executions if str(row.exec_id or "").strip() == target_id
        )
        if total_occurrences != matched_occurrences:
            blockers.append(
                f"exec_id {target_id} conflicts with Live execution evidence outside the matched order/account"
            )

    currencies = {str(row.currency or "").strip().upper() for row in matches}
    if len(currencies) != 1 or any(len(value) != 3 for value in currencies):
        blockers.append("matching Live executions do not share one valid currency")
    execution_currency = next(iter(currencies)) if len(currencies) == 1 else None

    total_quantity = 0.0
    gross = 0.0
    for row in matches:
        row_quantity = _positive(row.quantity)
        row_price = _positive(row.price)
        if row_quantity is None or row_price is None:
            blockers.append("matching Live execution contains non-positive or non-finite quantity/price")
            continue
        product = row_quantity * row_price
        if not math.isfinite(product):
            blockers.append(
                f"matching Live execution product overflowed to a non-finite value for exec_id {row.exec_id}"
            )
            continue
        total_quantity += row_quantity
        gross += product
        if not math.isfinite(gross):
            blockers.append("matching Live execution running gross total overflowed to a non-finite value")

    if expected_quantity is not None and total_quantity != expected_quantity:
        blockers.append(
            f"matching Live execution quantity does not equal expected total: {total_quantity} != {expected_quantity}"
        )

    matched_commissions: list[LiveCommissionEvidence] = []
    commission_total = 0.0
    for execution in matches:
        rows = [row for row in snapshot.commissions if row.exec_id == execution.exec_id]
        if len(rows) != 1:
            blockers.append(
                f"expected exactly one commission for exec_id {execution.exec_id}; found {len(rows)}"
            )
            continue
        commission = rows[0]
        parsed_commission = _finite(commission.commission)
        if parsed_commission is None:
            blockers.append(f"commission for exec_id {execution.exec_id} is non-finite")
            continue
        if execution_currency is None or commission.currency != execution_currency:
            blockers.append(
                f"commission currency for exec_id {execution.exec_id} does not match execution currency"
            )
            continue
        matched_commissions.append(commission)
        commission_total += parsed_commission
        if not math.isfinite(commission_total):
            blockers.append(
                f"running commission total overflowed to a non-finite value at exec_id {execution.exec_id}"
            )
            continue

    if blockers:
        return LivePostFillMatch(
            False,
            tuple(blockers),
            matches[0] if matches else None,
            matched_commissions[0] if matched_commissions else None,
            None,
            executions=tuple(matches),
            commissions=tuple(matched_commissions),
            filled_quantity=total_quantity if matches else None,
            vwap_price=(gross / total_quantity) if total_quantity > 0 else None,
            commission_total=commission_total if matched_commissions else None,
        )

    vwap = gross / total_quantity
    cash_effect = -(gross + commission_total) if normalized_side == "BUY" else gross - commission_total
    return LivePostFillMatch(
        True,
        (),
        matches[0],
        matched_commissions[0],
        cash_effect,
        executions=tuple(matches),
        commissions=tuple(matched_commissions),
        filled_quantity=total_quantity,
        vwap_price=vwap,
        commission_total=commission_total,
    )


def persist_live_postfill_snapshot(snapshot: IbkrLivePostFillSnapshot, *, report_path: Path = DEFAULT_REPORT_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ready": snapshot.ready,
        "attempted": snapshot.attempted,
        "connected": snapshot.connected,
        "endpoint_port": snapshot.endpoint_port,
        "account_fingerprint": snapshot.account_fingerprint,
        "executions": [asdict(row) for row in snapshot.executions],
        "commissions": [asdict(row) for row in snapshot.commissions],
        "blocked_reason": snapshot.blocked_reason,
        "errors": list(snapshot.errors),
        "raw_account_id_persisted": False,
        "connection_mode": "LIVE_READ_ONLY",
        "order_sent": False,
        "live_order_sent": False,
    }
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report_path)
