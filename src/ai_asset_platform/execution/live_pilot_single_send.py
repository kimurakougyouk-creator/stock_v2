"""Single-send transport for the first tightly bounded IBKR Live pilot.

This is intentionally *not* the normal strategy Live path. It can submit exactly
one LIMIT order only after all independently-audited preparation evidence is
ready, the exact one-shot authorization is consumed, and an irreversible
send-attempt marker is durably written. It never retries, cancels, modifies,
flattens, or closes an order automatically.

The raw IBKR account id is obtained from the same socket session used for the
order and is never persisted. Its SHA-256 fingerprint must equal the account
fingerprint pinned by the read-only preflight.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
from threading import Event, Thread
from typing import Callable

from ibapi.client import EClient
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_contracts import (
    build_ibkr_contract_spec,
    to_ibapi_contract,
)
from ai_asset_platform.brokers.ibkr_live_readonly_account import _account_fingerprint
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass
from ai_asset_platform.execution.live_pilot_emergency_stop import (
    DEFAULT_STOP_PATH,
    live_pilot_stop_is_active,
)
from ai_asset_platform.execution.live_pilot_one_shot_authorization import (
    DEFAULT_AUTHORIZATION_DIR,
    consume_live_pilot_authorization,
)
from ai_asset_platform.execution.live_pilot_same_run_preflight import (
    LivePilotSameRunPreflight,
)
from ai_asset_platform.execution.live_pilot_send_journal import (
    DEFAULT_JOURNAL_DIR,
    create_consumed_authorization_journal,
    mark_order_acknowledged,
    mark_unknown,
    record_send_attempt,
)
from ai_asset_platform.execution.live_pilot_source_cutover import (
    audit_live_pilot_source_cutover,
)
from ai_asset_platform.reports.live_operational_pilot_readiness import LIVE_PILOT_SCOPE


FINAL_SEND_CONFIRMATION_VALUE = "SEND_EXACTLY_ONE_LIVE_PILOT_NOW"
_VALID_LIVE_PORTS = {4001, 7496}
_ACCEPTED_STATUSES = {"PreSubmitted", "Submitted", "Filled"}


@dataclass(frozen=True)
class LivePilotSendRequest:
    intent_id: str
    ticker: str
    side: str
    quantity: int
    limit_price: float
    estimated_notional_jpy: float


@dataclass(frozen=True)
class LivePilotSendResult:
    status: str
    sent: bool
    acknowledged: bool
    order_id: int | None
    perm_id: int | None
    endpoint_port: int | None
    account_fingerprint: str | None
    broker_status: str | None
    recovery_required: bool
    message: str


class _LivePilotClient(EWrapper, EClient):
    """Minimal one-order Live client. It exposes no cancel/modify helper."""

    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.accounts_ready = Event()
        self.ack_ready = Event()
        self.next_order_id: int | None = None
        self.accounts: list[str] = []
        self.watched_order_id: int | None = None
        self.watched_account: str | None = None
        self.ack_perm_id: int | None = None
        self.broker_status: str | None = None
        self.order_error: str | None = None
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = int(orderId)
        self.connected_ready.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [item.strip() for item in str(accountsList).split(",") if item.strip()]
        self.accounts_ready.set()

    def orderStatus(  # noqa: N802
        self,
        orderId,
        status,
        filled,
        remaining,
        avgFillPrice,
        permId,
        parentId,
        lastFillPrice,
        clientId,
        whyHeld,
        mktCapPrice,
    ) -> None:
        if self.watched_order_id is None or int(orderId) != self.watched_order_id:
            return
        self.broker_status = str(status)
        try:
            perm = int(permId)
        except (TypeError, ValueError):
            perm = 0
        if self.broker_status in _ACCEPTED_STATUSES and perm > 0:
            self.ack_perm_id = perm
            self.ack_ready.set()

    def openOrder(self, orderId, contract, order, orderState) -> None:  # noqa: N802
        if self.watched_order_id is None or int(orderId) != self.watched_order_id:
            return
        if str(getattr(order, "account", "") or "").strip() != str(self.watched_account or ""):
            self.order_error = "broker acknowledgement account does not match the same-session account"
            self.ack_ready.set()
            return
        try:
            perm = int(getattr(order, "permId", 0) or 0)
        except (TypeError, ValueError):
            perm = 0
        if perm > 0:
            self.ack_perm_id = perm
            self.broker_status = self.broker_status or "OpenOrder"
            self.ack_ready.set()

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson="") -> None:  # noqa: N802
        text = f"{reqId}:{errorCode}:{errorString}"
        self.errors.append(text)
        if self.watched_order_id is not None:
            try:
                matching = int(reqId) == int(self.watched_order_id)
            except (TypeError, ValueError):
                matching = False
            if matching and int(errorCode) not in {2104, 2106, 2158}:
                self.order_error = text
                self.ack_ready.set()


def _instrument_for(ticker: str) -> InstrumentSpec:
    normalized = str(ticker or "").strip().upper()
    if normalized == "AAPL":
        return InstrumentSpec("AAPL", AssetClass.STOCK, exchange="SMART", currency="USD", verified_paper_test_quantity=1)
    if normalized == "SPY":
        return InstrumentSpec("SPY", AssetClass.ETF, exchange="SMART", currency="USD", verified_paper_test_quantity=1)
    if normalized == "9432.T":
        return InstrumentSpec("9432", AssetClass.STOCK, exchange="TSEJ", currency="JPY", verified_paper_test_quantity=100)
    raise ValueError("ticker is outside the exact first-Live-pilot scope")


def _positive(value: object, *, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be positive and finite") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return parsed


def _validate_request(request: LivePilotSendRequest, readiness_report: dict) -> tuple[str, str, int, float, float]:
    intent = str(request.intent_id or "").strip()
    if not intent:
        raise ValueError("intent_id is required")
    ticker = str(request.ticker or "").strip().upper()
    side = str(request.side or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    try:
        quantity = int(request.quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("quantity must be the exact bounded pilot quantity") from exc
    if LIVE_PILOT_SCOPE.get(ticker) != quantity:
        raise ValueError("quantity does not equal the exact bounded pilot quantity")
    limit_price = _positive(request.limit_price, name="limit_price")
    notional = _positive(request.estimated_notional_jpy, name="estimated_notional_jpy")
    if not isinstance(readiness_report, dict):
        raise PermissionError("operational readiness evidence is missing")
    expected = {
        "status": "READY_FOR_ONE_OPERATIONAL_PILOT",
        "operational_pilot_ready": True,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "order_sent": False,
        "live_order_sent": False,
    }
    for key, value in expected.items():
        observed = readiness_report.get(key)
        if key in {"ticker", "side"}:
            observed = str(observed or "").strip().upper()
        if observed != value:
            raise PermissionError(f"operational readiness binding mismatch: {key}")
    for key, expected_number in (("limit_price", limit_price), ("estimated_notional_jpy", notional)):
        observed = _positive(readiness_report.get(key), name=f"readiness.{key}")
        tolerance = max(0.01, abs(expected_number) * 1e-9)
        if abs(observed - expected_number) > tolerance:
            raise PermissionError(f"operational readiness binding mismatch: {key}")
    return intent, ticker, quantity, limit_price, notional


def _build_order(*, ticker: str, side: str, quantity: int, limit_price: float, account_id: str, intent_id: str):
    instrument = _instrument_for(ticker)
    contract = to_ibapi_contract(build_ibkr_contract_spec(instrument))
    order = Order()
    order.action = side
    order.totalQuantity = quantity
    order.orderType = "LMT"
    order.lmtPrice = limit_price
    order.tif = "DAY"
    order.outsideRth = False
    order.account = account_id
    order.orderRef = intent_id
    order.transmit = True
    return contract, order


def send_exactly_one_live_pilot(
    request: LivePilotSendRequest,
    *,
    nonce: str,
    expected_account_fingerprint: str,
    readiness_report: dict,
    same_run_preflight: LivePilotSameRunPreflight,
    expected_commit_sha: str,
    final_confirmation: str,
    authorization_dir: Path = DEFAULT_AUTHORIZATION_DIR,
    journal_dir: Path = DEFAULT_JOURNAL_DIR,
    stop_path: Path = DEFAULT_STOP_PATH,
    repository_root: Path = Path("."),
    timeout_seconds: float = 10.0,
    now: datetime | None = None,
    client_factory: Callable[[], _LivePilotClient] = _LivePilotClient,
) -> LivePilotSendResult:
    """Make at most one broker transport call for one fully-bound Live pilot.

    No retry is attempted under any outcome. A timeout, transport exception,
    broker-side error, or ambiguous acknowledgement becomes UNKNOWN and must be
    reconciled read-only.
    """
    if str(final_confirmation or "").strip() != FINAL_SEND_CONFIRMATION_VALUE:
        raise PermissionError("exact final one-send confirmation is missing")
    if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")

    intent, ticker, quantity, limit_price, notional = _validate_request(request, readiness_report)
    side = str(request.side).strip().upper()
    fingerprint = str(expected_account_fingerprint or "").strip().lower()
    if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
        raise ValueError("expected_account_fingerprint must be a SHA-256 hex digest")

    if not isinstance(same_run_preflight, LivePilotSameRunPreflight) or not same_run_preflight.ready:
        raise PermissionError("same-run preflight is not ready")
    if same_run_preflight.status != "READY_FOR_OPERATOR_AUTHORIZATION":
        raise PermissionError("same-run preflight status is not send-eligible")
    if str(same_run_preflight.ticker).strip().upper() != ticker:
        raise PermissionError("same-run preflight ticker mismatch")
    if not same_run_preflight.account_fingerprint_match:
        raise PermissionError("same-run account fingerprint is not pinned")
    endpoint_port = same_run_preflight.endpoint_port
    if endpoint_port not in _VALID_LIVE_PORTS:
        raise PermissionError("same-run preflight endpoint is not an audited Live endpoint")
    if not same_run_preflight.emergency_stop_clear or not same_run_preflight.live_global_lock_intact:
        raise PermissionError("pre-send safety lock is not intact")

    source = audit_live_pilot_source_cutover(
        expected_commit_sha=expected_commit_sha,
        repository_root=repository_root,
        now=now,
    )
    if not source.ready:
        raise PermissionError("audited source/PIN cutover is not ready")
    if live_pilot_stop_is_active(stop_path=stop_path):
        raise PermissionError("Live pilot emergency stop is active before connection")

    client = client_factory()
    try:
        try:
            client.connect("127.0.0.1", int(endpoint_port), 681)
        except OSError as exc:
            return LivePilotSendResult("BLOCKED_NOT_CONNECTED", False, False, None, None, endpoint_port, None, None, False, str(exc))
        Thread(
            target=run_ibapi_message_loop_safely,
            kwargs={"client": client, "errors": client.errors},
            daemon=True,
        ).start()
        if not client.connected_ready.wait(timeout_seconds):
            return LivePilotSendResult("BLOCKED_NO_NEXT_VALID_ID", False, False, None, None, endpoint_port, None, None, False, "nextValidId was not proven before timeout")
        order_id = client.next_order_id
        if order_id is None or int(order_id) <= 0:
            return LivePilotSendResult("BLOCKED_INVALID_ORDER_ID", False, False, None, None, endpoint_port, None, None, False, "nextValidId is not a positive order id")

        client.reqManagedAccts()
        if not client.accounts_ready.wait(timeout_seconds) or len(client.accounts) != 1:
            return LivePilotSendResult("BLOCKED_ACCOUNT_IDENTITY", False, False, None, None, endpoint_port, None, None, False, "same-session managed account identity is not exactly one account")
        raw_account_id = client.accounts[0]
        observed_fingerprint = _account_fingerprint(raw_account_id)
        if observed_fingerprint != fingerprint:
            return LivePilotSendResult("BLOCKED_ACCOUNT_FINGERPRINT", False, False, None, None, endpoint_port, observed_fingerprint, None, False, "same-session raw account fingerprint differs from pinned preflight account")

        contract, order = _build_order(
            ticker=ticker,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            account_id=raw_account_id,
            intent_id=intent,
        )

        consumed = consume_live_pilot_authorization(
            nonce=nonce,
            intent_id=intent,
            ticker=ticker,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            estimated_notional_jpy=notional,
            account_fingerprint=fingerprint,
            endpoint_port=int(endpoint_port),
            authorization_dir=authorization_dir,
            now=now,
        )
        create_consumed_authorization_journal(
            intent_id=intent,
            nonce=nonce,
            consumed_authorization=consumed,
            directory=journal_dir,
            now=now,
        )
        record_send_attempt(intent, directory=journal_dir, now=now)

        # Last possible stop check. The irreversible attempt is deliberately
        # spent first, so a stop arriving here can never be bypassed by retry.
        if live_pilot_stop_is_active(stop_path=stop_path):
            return LivePilotSendResult(
                "BLOCKED_STOP_AFTER_ATTEMPT",
                False,
                False,
                int(order_id),
                None,
                endpoint_port,
                observed_fingerprint,
                None,
                True,
                "emergency stop became active; attempt remains permanently spent",
            )

        client.watched_order_id = int(order_id)
        client.watched_account = raw_account_id
        try:
            client.placeOrder(int(order_id), contract, order)
        except Exception as exc:
            mark_unknown(intent, reason=f"placeOrder transport raised: {type(exc).__name__}", directory=journal_dir, now=now)
            return LivePilotSendResult("UNKNOWN", True, False, int(order_id), None, endpoint_port, observed_fingerprint, None, True, "transport outcome is unknown; no retry permitted")

        if not client.ack_ready.wait(timeout_seconds):
            mark_unknown(intent, reason="broker acknowledgement timed out", directory=journal_dir, now=now)
            return LivePilotSendResult("UNKNOWN", True, False, int(order_id), None, endpoint_port, observed_fingerprint, client.broker_status, True, "broker acknowledgement timed out; no retry permitted")
        if client.order_error or client.ack_perm_id is None or int(client.ack_perm_id) <= 0:
            mark_unknown(intent, reason=client.order_error or "broker acknowledgement lacked positive permId", directory=journal_dir, now=now)
            return LivePilotSendResult("UNKNOWN", True, False, int(order_id), None, endpoint_port, observed_fingerprint, client.broker_status, True, "broker state requires read-only reconciliation; no retry permitted")

        perm_id = int(client.ack_perm_id)
        mark_order_acknowledged(
            intent,
            order_id=int(order_id),
            perm_id=perm_id,
            directory=journal_dir,
            now=now,
        )
        return LivePilotSendResult(
            "ORDER_ACKNOWLEDGED",
            True,
            True,
            int(order_id),
            perm_id,
            endpoint_port,
            observed_fingerprint,
            client.broker_status,
            True,
            "exactly one Live pilot order was acknowledged; post-fill proof is still required",
        )
    finally:
        try:
            if client.isConnected():
                client.disconnect()
        except Exception:
            pass
