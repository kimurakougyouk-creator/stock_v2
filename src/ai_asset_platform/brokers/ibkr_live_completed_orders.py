"""Read-only IBKR Live completed-order evidence for pilot recovery.

This module may open a Live socket only after the exact read-only confirmation.
It requests managed-account identity and completed-order history from one
explicitly authorized Live endpoint.  It never places, modifies, cancels,
retries, flattens, closes, or previews an order.

Raw account identifiers are used only in memory and are never persisted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    CONFIRMATION_ENV,
    CONFIRMATION_VALUE,
    LIVE_GATEWAY_PORT,
    LIVE_TWS_PORT,
    _account_fingerprint,
)
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely


DEFAULT_REPORT_PATH = Path("results/ibkr_live_completed_orders_latest.json")
REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IbkrLiveCompletedOrderEvidence:
    order_id: int
    perm_id: int
    client_id: int
    symbol: str
    sec_type: str
    currency: str
    exchange: str
    action: str
    quantity: float
    order_type: str
    limit_price: float | None
    status: str
    completed_status: str
    completed_time: str
    order_ref: str
    account_fingerprint: str


@dataclass(frozen=True)
class IbkrLiveCompletedOrdersSnapshot:
    attempted: bool
    connected: bool
    ready: bool
    endpoint_port: int | None
    account_fingerprint: str | None = None
    orders: tuple[IbkrLiveCompletedOrderEvidence, ...] = ()
    blocked_reason: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    order_sent: bool = False
    cancel_sent: bool = False
    modify_sent: bool = False
    live_order_sent: bool = False


def _dedupe_exact_completed_orders(
    orders: list[IbkrLiveCompletedOrderEvidence],
) -> tuple[IbkrLiveCompletedOrderEvidence, ...]:
    """Drop only byte-for-byte-equivalent normalized callback evidence.

    Conflicting callbacks for the same broker identity must remain distinct so
    downstream reconciliation sees the ambiguity and fails closed.
    """
    return tuple(dict.fromkeys(orders))


def _parse_error(args: tuple[object, ...]) -> tuple[int, str] | None:
    if len(args) >= 4:
        code, message = args[1], args[2]
    elif len(args) >= 2:
        code, message = args[0], args[1]
    else:
        return None
    try:
        return int(code), str(message)
    except (TypeError, ValueError, OverflowError):
        return None


def _positive_finite_or_none(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


class _LiveCompletedOrdersProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.accounts_ready = Event()
        self.orders_ready = Event()
        self.accounts: list[str] = []
        self.orders: list[IbkrLiveCompletedOrderEvidence] = []
        self.errors: list[str] = []
        self.fatal_error: str | None = None
        self.invalid_order_evidence = False

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [
            item.strip() for item in str(accountsList).split(",") if item.strip()
        ]
        self.accounts_ready.set()

    def completedOrder(self, contract, order, orderState) -> None:  # noqa: N802
        if len(self.accounts) != 1:
            return
        raw_account = str(getattr(order, "account", "") or "").strip()
        if not raw_account or raw_account != self.accounts[0]:
            return
        raw_order_id = getattr(order, "orderId", None)
        raw_perm_id = getattr(order, "permId", None)
        raw_client_id = getattr(order, "clientId", None)
        if (
            not isinstance(raw_order_id, int)
            or isinstance(raw_order_id, bool)
            or not isinstance(raw_perm_id, int)
            or isinstance(raw_perm_id, bool)
            or not isinstance(raw_client_id, int)
            or isinstance(raw_client_id, bool)
        ):
            self.invalid_order_evidence = True
            return
        order_id = raw_order_id
        perm_id = raw_perm_id
        client_id = raw_client_id
        try:
            quantity = float(getattr(order, "totalQuantity", 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            self.invalid_order_evidence = True
            return
        if (
            order_id <= 0
            or perm_id <= 0
            or client_id < 0
            or not math.isfinite(quantity)
            or quantity <= 0
        ):
            self.invalid_order_evidence = True
            return
        action = str(getattr(order, "action", "") or "").strip().upper()
        action = {"BOT": "BUY", "SLD": "SELL"}.get(action, action)
        self.orders.append(
            IbkrLiveCompletedOrderEvidence(
                order_id=order_id,
                perm_id=perm_id,
                client_id=client_id,
                symbol=str(getattr(contract, "symbol", "") or "").strip().upper(),
                sec_type=str(getattr(contract, "secType", "") or "").strip().upper(),
                currency=str(getattr(contract, "currency", "") or "").strip().upper(),
                exchange=str(
                    getattr(contract, "primaryExchange", "")
                    or getattr(contract, "exchange", "")
                    or ""
                ).strip().upper(),
                action=action,
                quantity=quantity,
                order_type=str(getattr(order, "orderType", "") or "").strip().upper(),
                limit_price=_positive_finite_or_none(
                    getattr(order, "lmtPrice", None)
                ),
                status=str(getattr(orderState, "status", "") or "").strip(),
                completed_status=str(
                    getattr(orderState, "completedStatus", "") or ""
                ).strip(),
                completed_time=str(
                    getattr(orderState, "completedTime", "") or ""
                ).strip(),
                order_ref=str(getattr(order, "orderRef", "") or "").strip(),
                account_fingerprint=_account_fingerprint(raw_account),
            )
        )

    def completedOrdersEnd(self) -> None:  # noqa: N802
        self.orders_ready.set()

    def error(self, reqId, *args):
        parsed = _parse_error(args)
        if parsed is None:
            return
        code, message = parsed
        rendered = f"{code}: {message}"
        self.errors.append(rendered)
        if code in {326, 502, 503, 504, 1100}:
            self.fatal_error = rendered
            self.connected_ready.set()
            self.accounts_ready.set()
            self.orders_ready.set()


def _blocked(reason: str) -> IbkrLiveCompletedOrdersSnapshot:
    return IbkrLiveCompletedOrdersSnapshot(
        attempted=False,
        connected=False,
        ready=False,
        endpoint_port=None,
        account_fingerprint=None,
        orders=(),
        blocked_reason=reason,
        errors=(),
        order_sent=False,
        cancel_sent=False,
        modify_sent=False,
        live_order_sent=False,
    )


def preview_ibkr_live_completed_orders(
    *,
    timeout: float = 10.0,
    confirmation: str | None = None,
    endpoint_port: int | None = None,
) -> IbkrLiveCompletedOrdersSnapshot:
    """Collect completed Live orders from one audited endpoint, read-only."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    supplied = (
        str(confirmation).strip()
        if confirmation is not None
        else os.getenv(CONFIRMATION_ENV, "").strip()
    )
    if supplied != CONFIRMATION_VALUE:
        return _blocked("exact Live read-only confirmation is missing")
    if endpoint_port not in {LIVE_GATEWAY_PORT, LIVE_TWS_PORT}:
        raise ValueError("endpoint_port must identify one audited Live endpoint")

    probe = _LiveCompletedOrdersProbe()
    try:
        try:
            probe.connect("127.0.0.1", int(endpoint_port), 771)
        except OSError as exc:
            return IbkrLiveCompletedOrdersSnapshot(
                attempted=True,
                connected=False,
                ready=False,
                endpoint_port=None,
                account_fingerprint=None,
                orders=(),
                blocked_reason="Live completed-order endpoint connection failed",
                errors=(f"{endpoint_port}: {exc}",),
            )
        Thread(
            target=run_ibapi_message_loop_safely,
            kwargs={"client": probe, "errors": probe.errors},
            daemon=True,
        ).start()
        if not probe.connected_ready.wait(timeout) or probe.fatal_error:
            return IbkrLiveCompletedOrdersSnapshot(
                attempted=True,
                connected=False,
                ready=False,
                endpoint_port=None,
                account_fingerprint=None,
                orders=(),
                blocked_reason="Live completed-order endpoint was not ready",
                errors=tuple(probe.errors),
            )

        probe.reqManagedAccts()
        if not probe.accounts_ready.wait(timeout) or len(probe.accounts) != 1:
            return IbkrLiveCompletedOrdersSnapshot(
                attempted=True,
                connected=True,
                ready=False,
                endpoint_port=int(endpoint_port),
                account_fingerprint=None,
                orders=(),
                blocked_reason="expected exactly one managed Live account",
                errors=tuple(probe.errors),
            )
        fingerprint = _account_fingerprint(probe.accounts[0])

        probe.reqCompletedOrders(False)
        if not probe.orders_ready.wait(timeout) or probe.fatal_error:
            return IbkrLiveCompletedOrdersSnapshot(
                attempted=True,
                connected=True,
                ready=False,
                endpoint_port=int(endpoint_port),
                account_fingerprint=fingerprint,
                orders=(),
                blocked_reason="Live completed-order snapshot did not complete",
                errors=tuple(probe.errors),
            )

        if probe.invalid_order_evidence:
            return IbkrLiveCompletedOrdersSnapshot(
                attempted=True,
                connected=True,
                ready=False,
                endpoint_port=int(endpoint_port),
                account_fingerprint=fingerprint,
                orders=(),
                blocked_reason=(
                    "Live completed-order snapshot contained malformed order evidence"
                ),
                errors=tuple(probe.errors),
                order_sent=False,
                cancel_sent=False,
                modify_sent=False,
                live_order_sent=False,
            )

        deduped = _dedupe_exact_completed_orders(probe.orders)
        return IbkrLiveCompletedOrdersSnapshot(
            attempted=True,
            connected=True,
            ready=True,
            endpoint_port=int(endpoint_port),
            account_fingerprint=fingerprint,
            orders=deduped,
            blocked_reason=None,
            errors=tuple(probe.errors),
            order_sent=False,
            cancel_sent=False,
            modify_sent=False,
            live_order_sent=False,
        )
    finally:
        if probe.isConnected():
            probe.disconnect()


def persist_live_completed_orders(
    snapshot: IbkrLiveCompletedOrdersSnapshot,
    *,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "attempted": snapshot.attempted,
        "connected": snapshot.connected,
        "ready": snapshot.ready,
        "endpoint_port": snapshot.endpoint_port,
        "account_fingerprint": snapshot.account_fingerprint,
        "raw_account_id_persisted": False,
        "completed_order_count": len(snapshot.orders),
        "orders": [asdict(item) for item in snapshot.orders],
        "blocked_reason": snapshot.blocked_reason,
        "errors": list(snapshot.errors),
        "connection_mode": "LIVE_READ_ONLY",
        "broker_connection_used": snapshot.attempted,
        "order_sent": False,
        "cancel_sent": False,
        "modify_sent": False,
        "live_order_sent": False,
    }
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)
