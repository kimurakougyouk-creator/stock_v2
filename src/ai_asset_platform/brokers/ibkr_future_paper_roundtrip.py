"""Controlled one-contract futures Paper round-trip for ESU6.

This is a dedicated Paper-only verification flow. It requires an exact human
confirmation string, the exact broker-resolved ESU6 contract, a flat starting
position, no matching open order, and intact Live safety locks. It submits one
BUY 1 MKT order and, only after a confirmed full fill, submits one SELL 1 MKT
order to return the broker position to flat. No automatic re-send occurs after
an uncertain timeout. This module never enables Live Trading and does not
promote FUTURE capability.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Event

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_future_contracts import (
    VerifiedFutureContractInput,
    build_verified_future_contract,
)
from ai_asset_platform.brokers.ibkr_probe_thread import start_guarded_ibapi_loop
from ai_asset_platform.core.settings import SETTINGS

SYMBOL = "ES"
EXCHANGE = "CME"
CURRENCY = "USD"
EXPIRY = "20260918"
MULTIPLIER = "50"
LOCAL_SYMBOL = "ESU6"
CON_ID = 649180671
QUANTITY = 1
CONFIRMATION_TEXT = "YES_BUY_AND_SELL_ONE_ESU6_PAPER_TO_FLAT"


@dataclass(frozen=True)
class FuturePaperRoundTripResult:
    attempted: bool
    reason: str
    endpoint_port: int | None
    start_quantity: float | None
    buy_order_id: int | None
    buy_filled: float
    buy_avg_price: float | None
    sell_order_id: int | None
    sell_filled: float
    sell_avg_price: float | None
    end_quantity: float | None
    broker_flat_after: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    real_paper_order_sent: bool = False
    live_order_sent: bool = False


class _RoundTripProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.position_ready = Event()
        self.open_orders_ready = Event()
        self.buy_done = Event()
        self.sell_done = Event()
        self.next_order_id: int | None = None
        self.positions: list[tuple[str, str, float]] = []
        self.open_order_symbols: list[tuple[str, str, int]] = []
        self.statuses: dict[int, tuple[str, float, float | None]] = {}
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = int(orderId)
        self.connected_ready.set()

    def position(self, account, contract, pos, avgCost):  # noqa: N802
        self.positions.append(
            (
                str(getattr(contract, "localSymbol", "") or "").upper(),
                str(getattr(contract, "secType", "") or "").upper(),
                float(pos),
            )
        )

    def positionEnd(self):  # noqa: N802
        self.position_ready.set()

    def openOrder(self, orderId, contract, order, orderState):  # noqa: N802
        self.open_order_symbols.append(
            (
                str(getattr(contract, "localSymbol", "") or "").upper(),
                str(getattr(contract, "secType", "") or "").upper(),
                int(orderId),
            )
        )

    def openOrderEnd(self):  # noqa: N802
        self.open_orders_ready.set()

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):  # noqa: N802,E501
        oid = int(orderId)
        stat = str(status).upper()
        avg = float(avgFillPrice) if float(avgFillPrice or 0.0) > 0 else None
        self.statuses[oid] = (stat, float(filled), avg)
        if self.next_order_id is not None:
            if oid == self.next_order_id and stat in {"FILLED", "CANCELLED", "INACTIVE"}:
                self.buy_done.set()
            if oid == self.next_order_id + 1 and stat in {"FILLED", "CANCELLED", "INACTIVE"}:
                self.sell_done.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
        message = f"{errorCode}: {errorString}"
        self.errors.append(message)
        if int(errorCode) in {201, 202, 321, 322, 323, 326, 502, 503, 504, 1100}:
            self.buy_done.set()
            self.sell_done.set()
            if int(errorCode) in {502, 503, 504, 1100}:
                self.connected_ready.set()


def _contract() -> Contract:
    return build_verified_future_contract(
        VerifiedFutureContractInput(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            currency=CURRENCY,
            expiry=EXPIRY,
            multiplier=MULTIPLIER,
            local_symbol=LOCAL_SYMBOL,
            con_id=CON_ID,
        )
    )


def _position_quantity(probe: _RoundTripProbe) -> float:
    matches = [qty for local, sec, qty in probe.positions if local == LOCAL_SYMBOL and sec == "FUT"]
    if len(matches) > 1:
        raise RuntimeError("multiple ESU6 futures positions returned by broker")
    return 0.0 if not matches else float(matches[0])


def _refresh_positions(probe: _RoundTripProbe, timeout: float) -> float | None:
    probe.positions.clear()
    probe.position_ready.clear()
    probe.reqPositions()
    if not probe.position_ready.wait(timeout):
        return None
    try:
        return _position_quantity(probe)
    finally:
        probe.cancelPositions()


def _matching_open_order_exists(probe: _RoundTripProbe, timeout: float) -> bool:
    probe.open_order_symbols.clear()
    probe.open_orders_ready.clear()
    probe.reqOpenOrders()
    if not probe.open_orders_ready.wait(timeout):
        raise RuntimeError("open-order verification timed out")
    return any(local == LOCAL_SYMBOL and sec == "FUT" for local, sec, _ in probe.open_order_symbols)


def _market_order(side: str, order_ref: str) -> Order:
    order = Order()
    order.action = side
    order.orderType = "MKT"
    order.totalQuantity = QUANTITY
    order.tif = "DAY"
    order.whatIf = False
    order.transmit = True
    order.orderRef = order_ref
    return order


def run_future_paper_roundtrip(*, timeout: float = 20.0) -> FuturePaperRoundTripResult:
    if not SETTINGS.enable_ibkr_paper:
        return FuturePaperRoundTripResult(False, "IBKR Paper is not explicitly enabled", None, None, None, 0.0, None, None, 0.0, None, None, False)
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return FuturePaperRoundTripResult(False, "Live Trading safety lock is not intact", None, None, None, 0.0, None, None, 0.0, None, None, False)
    if os.getenv("IBKR_FUTURE_E2E_CONFIRM", "").strip() != CONFIRMATION_TEXT:
        return FuturePaperRoundTripResult(False, "exact ESU6 Paper E2E confirmation is missing", None, None, None, 0.0, None, None, 0.0, None, None, False)

    cfg = create_ibkr_paper_config(use_gateway=True)
    probe = _RoundTripProbe()
    buy_order_id: int | None = None
    sell_order_id: int | None = None
    buy_filled = 0.0
    sell_filled = 0.0
    buy_avg: float | None = None
    sell_avg: float | None = None
    start_qty: float | None = None
    end_qty: float | None = None
    sent_any = False
    try:
        probe.connect(cfg.host, cfg.port, cfg.client_id + 280)
        start_guarded_ibapi_loop(probe.run, name="ibkr-future-paper-roundtrip")
        if not probe.connected_ready.wait(timeout) or probe.next_order_id is None:
            return FuturePaperRoundTripResult(False, "IBKR Paper handshake failed", cfg.port, None, None, 0.0, None, None, 0.0, None, None, False, tuple(probe.errors))

        start_qty = _refresh_positions(probe, timeout)
        if start_qty is None:
            return FuturePaperRoundTripResult(False, "starting broker position snapshot timed out", cfg.port, None, None, 0.0, None, None, 0.0, None, None, False, tuple(probe.errors))
        if abs(start_qty) > 1e-9:
            return FuturePaperRoundTripResult(False, f"ESU6 broker position must start flat; found {start_qty:g}", cfg.port, start_qty, None, 0.0, None, None, 0.0, None, start_qty, False, tuple(probe.errors))
        if _matching_open_order_exists(probe, timeout):
            return FuturePaperRoundTripResult(False, "an ESU6 open order already exists", cfg.port, start_qty, None, 0.0, None, None, 0.0, None, start_qty, False, tuple(probe.errors))

        contract = _contract()
        buy_order_id = int(probe.next_order_id)
        probe.placeOrder(buy_order_id, contract, _market_order("BUY", "stock_v2-future-paper-e2e-buy"))
        sent_any = True
        probe.buy_done.wait(timeout)
        buy_status = probe.statuses.get(buy_order_id)
        if buy_status is None or buy_status[0] != "FILLED" or abs(buy_status[1] - 1.0) > 1e-9:
            end_qty = _refresh_positions(probe, timeout)
            return FuturePaperRoundTripResult(True, "BUY outcome is not a confirmed full fill; no automatic resend/SELL performed", cfg.port, start_qty, buy_order_id, 0.0 if buy_status is None else buy_status[1], None if buy_status is None else buy_status[2], None, 0.0, None, end_qty, bool(end_qty is not None and abs(end_qty) <= 1e-9), tuple(probe.errors), True, False)
        buy_filled = buy_status[1]
        buy_avg = buy_status[2]

        held_qty = _refresh_positions(probe, timeout)
        if held_qty is None or abs(held_qty - 1.0) > 1e-9:
            return FuturePaperRoundTripResult(True, "BUY filled but broker position did not verify exactly +1; close not sent", cfg.port, start_qty, buy_order_id, buy_filled, buy_avg, None, 0.0, None, held_qty, False, tuple(probe.errors), True, False)

        if _matching_open_order_exists(probe, timeout):
            return FuturePaperRoundTripResult(True, "unexpected ESU6 open order exists after BUY; close not sent", cfg.port, start_qty, buy_order_id, buy_filled, buy_avg, None, 0.0, None, held_qty, False, tuple(probe.errors), True, False)

        sell_order_id = buy_order_id + 1
        probe.placeOrder(sell_order_id, contract, _market_order("SELL", "stock_v2-future-paper-e2e-flat"))
        probe.sell_done.wait(timeout)
        sell_status = probe.statuses.get(sell_order_id)
        if sell_status is not None:
            sell_filled = sell_status[1]
            sell_avg = sell_status[2]

        # Verify broker flat directly; do not resend if SELL outcome is uncertain.
        for _ in range(4):
            end_qty = _refresh_positions(probe, timeout)
            if end_qty is not None and abs(end_qty) <= 1e-9:
                break
            time.sleep(1.0)
        flat = bool(end_qty is not None and abs(end_qty) <= 1e-9)
        reason = "futures Paper round-trip completed and broker is flat" if flat else "SELL sent but broker flat state is not confirmed; no automatic resend"
        return FuturePaperRoundTripResult(True, reason, cfg.port, start_qty, buy_order_id, buy_filled, buy_avg, sell_order_id, sell_filled, sell_avg, end_qty, flat, tuple(probe.errors), sent_any, False)
    finally:
        if probe.isConnected():
            probe.disconnect()


def main() -> int:
    result = run_future_paper_roundtrip()
    print("===== IBKR PAPER FUTURES ROUND-TRIP E2E =====")
    print("ATTEMPTED             :", result.attempted)
    print("REASON                :", result.reason)
    print("ENDPOINT PORT         :", result.endpoint_port)
    print("TARGET                :", f"{LOCAL_SYMBOL} / {EXCHANGE} / {CURRENCY}")
    print("START QTY             :", result.start_quantity)
    print("BUY ORDER ID          :", result.buy_order_id)
    print("BUY FILLED            :", result.buy_filled)
    print("BUY AVG PRICE         :", result.buy_avg_price)
    print("SELL ORDER ID         :", result.sell_order_id)
    print("SELL FILLED           :", result.sell_filled)
    print("SELL AVG PRICE        :", result.sell_avg_price)
    print("END QTY               :", result.end_quantity)
    print("BROKER FLAT AFTER     :", result.broker_flat_after)
    print("ERRORS                :", list(result.errors))
    print("REAL PAPER ORDER SENT :", result.real_paper_order_sent)
    print("LIVE ORDER SENT       :", result.live_order_sent)
    return 0 if result.attempted and result.broker_flat_after and not result.live_order_sent else 2


if __name__ == "__main__":
    raise SystemExit(main())
