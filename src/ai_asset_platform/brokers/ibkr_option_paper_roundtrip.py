"""Controlled one-contract SPY option Paper round-trip.

Paper-only verification for the exact SPY option already proven by What-If.
The flow is fail-closed: Paper must be explicitly enabled, Live locks must be
intact, the exact confirmation string must be present, the broker-resolved
contract identity must match the pinned evidence, the starting broker position
must be flat, and no matching open order may exist. It never automatically
retries an uncertain order outcome.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_option_discovery import discover_ibkr_paper_option
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely
from ai_asset_platform.core.settings import SETTINGS

SYMBOL = "SPY"
EXCHANGE = "SMART"
CURRENCY = "USD"
EXPIRY = "20260828"
STRIKE = 765.0
RIGHT = "C"
MULTIPLIER = "100"
LOCAL_SYMBOL = "SPY   260828C00765000"
CON_ID = 900369377
QUANTITY = 1
CONFIRMATION_TEXT = "YES_BUY_AND_SELL_ONE_SPY_OPTION_PAPER_TO_FLAT"
_FATAL_ERROR_CODES = {201, 202, 321, 322, 323, 326, 502, 503, 504, 1100}


@dataclass(frozen=True)
class OptionPaperRoundTripResult:
    attempted: bool
    reason: str
    endpoint_port: int | None
    local_symbol: str | None
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

    @property
    def ready(self) -> bool:
        return (
            self.attempted
            and abs(self.buy_filled - QUANTITY) <= 1e-9
            and abs(self.sell_filled - QUANTITY) <= 1e-9
            and self.broker_flat_after
            and self.real_paper_order_sent
            and not self.live_order_sent
        )


class _Probe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready = Event()
        self.position_ready = Event()
        self.open_ready = Event()
        self.done = Event()
        self.next_id: int | None = None
        self.positions: list[tuple[str, str, float]] = []
        self.open_orders: list[tuple[str, str, int]] = []
        self.statuses: dict[int, tuple[str, float, float | None]] = {}
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_id = int(orderId)
        self.ready.set()

    def position(self, account, contract, pos, avgCost) -> None:  # noqa: N802
        self.positions.append(
            (
                str(getattr(contract, "localSymbol", "") or "").upper(),
                str(getattr(contract, "secType", "") or "").upper(),
                float(pos),
            )
        )

    def positionEnd(self) -> None:  # noqa: N802
        self.position_ready.set()

    def openOrder(self, orderId, contract, order, orderState) -> None:  # noqa: N802
        self.open_orders.append(
            (
                str(getattr(contract, "localSymbol", "") or "").upper(),
                str(getattr(contract, "secType", "") or "").upper(),
                int(orderId),
            )
        )

    def openOrderEnd(self) -> None:  # noqa: N802
        self.open_ready.set()

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
        avg = float(avgFillPrice) if float(avgFillPrice or 0.0) > 0 else None
        self.statuses[int(orderId)] = (str(status).upper(), float(filled), avg)
        if str(status).upper() in {"FILLED", "CANCELLED", "INACTIVE"}:
            self.done.set()

    def error(
        self,
        reqId,
        errorTime,
        errorCode,
        errorString,
        advancedOrderRejectJson="",
    ) -> None:
        message = f"{errorCode}: {errorString}"
        self.errors.append(message)
        if int(errorCode) in _FATAL_ERROR_CODES:
            self.done.set()
            if int(errorCode) in {502, 503, 504, 1100}:
                self.ready.set()


def _verified_target():
    result = discover_ibkr_paper_option(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        currency=CURRENCY,
        expiry=EXPIRY,
        strike=STRIKE,
        right=RIGHT,
        multiplier=MULTIPLIER,
        timeout=10.0,
    )
    matches = [
        c
        for c in result.candidates
        if c.local_symbol == LOCAL_SYMBOL
        and c.expiry == EXPIRY
        and c.strike == STRIKE
        and str(c.right).upper() == RIGHT
        and str(c.multiplier) == MULTIPLIER
        and c.con_id == CON_ID
    ]
    if len(matches) != 1:
        return result.endpoint_port, None, tuple(result.errors)
    return result.endpoint_port, matches[0], tuple(result.errors)


def _contract(candidate) -> Contract:
    contract = Contract()
    contract.conId = int(candidate.con_id)
    contract.symbol = SYMBOL
    contract.secType = "OPT"
    contract.exchange = EXCHANGE
    contract.currency = CURRENCY
    contract.localSymbol = str(candidate.local_symbol)
    contract.lastTradeDateOrContractMonth = str(candidate.expiry)
    contract.strike = float(candidate.strike)
    contract.right = str(candidate.right)
    contract.multiplier = str(candidate.multiplier)
    return contract


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


def _position_quantity(probe: _Probe) -> float:
    matches = [
        qty
        for local, sec_type, qty in probe.positions
        if local == LOCAL_SYMBOL.upper() and sec_type == "OPT"
    ]
    if not matches:
        return 0.0

    unique = {round(float(qty), 12) for qty in matches}
    if len(unique) == 1:
        return float(matches[-1])

    raise RuntimeError(
        "conflicting matching SPY option position quantities returned: "
        + ", ".join(str(qty) for qty in matches)
    )


def _refresh_positions(probe: _Probe, timeout: float) -> float | None:
    probe.positions.clear()
    probe.position_ready.clear()
    probe.reqPositions()
    if not probe.position_ready.wait(timeout):
        return None
    try:
        return _position_quantity(probe)
    finally:
        probe.cancelPositions()


def _matching_open_order_exists(probe: _Probe, timeout: float) -> bool:
    probe.open_orders.clear()
    probe.open_ready.clear()
    probe.reqOpenOrders()
    if not probe.open_ready.wait(timeout):
        raise RuntimeError("open-order verification timed out")
    return any(
        local == LOCAL_SYMBOL.upper() and sec_type == "OPT"
        for local, sec_type, _ in probe.open_orders
    )


def _empty(reason: str) -> OptionPaperRoundTripResult:
    return OptionPaperRoundTripResult(
        attempted=False,
        reason=reason,
        endpoint_port=None,
        local_symbol=None,
        start_quantity=None,
        buy_order_id=None,
        buy_filled=0.0,
        buy_avg_price=None,
        sell_order_id=None,
        sell_filled=0.0,
        sell_avg_price=None,
        end_quantity=None,
        broker_flat_after=False,
    )


def run_option_paper_roundtrip(*, timeout: float = 25.0) -> OptionPaperRoundTripResult:
    if not SETTINGS.enable_ibkr_paper:
        return _empty("IBKR Paper is not explicitly enabled")
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return _empty("Live Trading safety lock is not intact")
    if os.getenv("IBKR_OPTION_E2E_CONFIRM", "").strip() != CONFIRMATION_TEXT:
        return _empty("exact SPY option Paper E2E confirmation is missing")

    endpoint_port, candidate, discovery_errors = _verified_target()
    if candidate is None:
        return OptionPaperRoundTripResult(
            False,
            "exact proven SPY option identity was not returned by broker",
            endpoint_port,
            None,
            None,
            None,
            0.0,
            None,
            None,
            0.0,
            None,
            None,
            False,
            discovery_errors,
        )

    cfg = create_ibkr_paper_config(use_gateway=(endpoint_port == 4002))
    probe = _Probe()
    local_symbol = str(candidate.local_symbol)
    sent_any = False
    start_qty: float | None = None
    end_qty: float | None = None
    try:
        probe.connect(cfg.host, cfg.port, cfg.client_id + 296)
        Thread(
            target=run_ibapi_message_loop_safely,
            kwargs={"client": probe, "errors": probe.errors},
            daemon=True,
        ).start()
        if not probe.ready.wait(timeout) or probe.next_id is None:
            return OptionPaperRoundTripResult(
                False,
                "IBKR Paper handshake failed",
                cfg.port,
                local_symbol,
                None,
                None,
                0.0,
                None,
                None,
                0.0,
                None,
                None,
                False,
                discovery_errors + tuple(probe.errors),
            )

        start_qty = _refresh_positions(probe, timeout)
        if start_qty is None:
            return OptionPaperRoundTripResult(
                False,
                "starting broker position snapshot timed out",
                cfg.port,
                local_symbol,
                None,
                None,
                0.0,
                None,
                None,
                0.0,
                None,
                None,
                False,
                discovery_errors + tuple(probe.errors),
            )
        if abs(start_qty) > 1e-9:
            return OptionPaperRoundTripResult(
                False,
                f"option broker position must start flat; found {start_qty:g}",
                cfg.port,
                local_symbol,
                start_qty,
                None,
                0.0,
                None,
                None,
                0.0,
                None,
                start_qty,
                False,
                discovery_errors + tuple(probe.errors),
            )
        if _matching_open_order_exists(probe, timeout):
            return OptionPaperRoundTripResult(
                False,
                "matching option open order already exists",
                cfg.port,
                local_symbol,
                start_qty,
                None,
                0.0,
                None,
                None,
                0.0,
                None,
                start_qty,
                False,
                discovery_errors + tuple(probe.errors),
            )

        contract = _contract(candidate)
        buy_order_id = int(probe.next_id)
        probe.done.clear()
        probe.placeOrder(
            buy_order_id,
            contract,
            _market_order("BUY", "stock_v2-option-paper-e2e-buy"),
        )
        sent_any = True
        probe.done.wait(timeout)
        buy_status = probe.statuses.get(buy_order_id)
        if (
            buy_status is None
            or buy_status[0] != "FILLED"
            or abs(buy_status[1] - QUANTITY) > 1e-9
        ):
            end_qty = _refresh_positions(probe, timeout)
            return OptionPaperRoundTripResult(
                True,
                "BUY outcome is not a confirmed full fill; no automatic resend/SELL performed",
                cfg.port,
                local_symbol,
                start_qty,
                buy_order_id,
                0.0 if buy_status is None else buy_status[1],
                None if buy_status is None else buy_status[2],
                None,
                0.0,
                None,
                end_qty,
                bool(end_qty is not None and abs(end_qty) <= 1e-9),
                discovery_errors + tuple(probe.errors),
                True,
                False,
            )

        held_qty = _refresh_positions(probe, timeout)
        if held_qty is None or abs(held_qty - QUANTITY) > 1e-9:
            return OptionPaperRoundTripResult(
                True,
                "BUY filled but broker position did not verify exactly +1; close not sent",
                cfg.port,
                local_symbol,
                start_qty,
                buy_order_id,
                buy_status[1],
                buy_status[2],
                None,
                0.0,
                None,
                held_qty,
                False,
                discovery_errors + tuple(probe.errors),
                True,
                False,
            )
        if _matching_open_order_exists(probe, timeout):
            return OptionPaperRoundTripResult(
                True,
                "unexpected matching option open order exists after BUY; close not sent",
                cfg.port,
                local_symbol,
                start_qty,
                buy_order_id,
                buy_status[1],
                buy_status[2],
                None,
                0.0,
                None,
                held_qty,
                False,
                discovery_errors + tuple(probe.errors),
                True,
                False,
            )

        sell_order_id = buy_order_id + 1
        probe.done.clear()
        probe.placeOrder(
            sell_order_id,
            contract,
            _market_order("SELL", "stock_v2-option-paper-e2e-flat"),
        )
        probe.done.wait(timeout)
        sell_status = probe.statuses.get(sell_order_id)
        sell_confirmed = bool(
            sell_status is not None
            and sell_status[0] == "FILLED"
            and abs(sell_status[1] - QUANTITY) <= 1e-9
        )

        for _ in range(4):
            end_qty = _refresh_positions(probe, timeout)
            if end_qty is not None and abs(end_qty) <= 1e-9:
                break
            time.sleep(1.0)

        flat = bool(end_qty is not None and abs(end_qty) <= 1e-9)
        if sell_confirmed and flat:
            reason = "option Paper round-trip completed and broker is flat"
        elif not sell_confirmed:
            reason = "SELL outcome is not a confirmed full fill; no automatic resend"
        else:
            reason = "SELL filled but broker flat state is not confirmed; no automatic resend"
        return OptionPaperRoundTripResult(
            True,
            reason,
            cfg.port,
            local_symbol,
            start_qty,
            buy_order_id,
            buy_status[1],
            buy_status[2],
            sell_order_id,
            0.0 if sell_status is None else sell_status[1],
            None if sell_status is None else sell_status[2],
            end_qty,
            flat,
            discovery_errors + tuple(probe.errors),
            sent_any,
            False,
        )
    finally:
        if probe.isConnected():
            probe.disconnect()


def main() -> int:
    result = run_option_paper_roundtrip()
    print("===== IBKR PAPER SPY OPTION ROUND-TRIP E2E =====")
    print("ATTEMPTED             :", result.attempted)
    print("REASON                :", result.reason)
    print("ENDPOINT PORT         :", result.endpoint_port)
    print("LOCAL SYMBOL          :", result.local_symbol)
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
    print("READY                 :", result.ready)
    print("REAL PAPER ORDER SENT :", result.real_paper_order_sent)
    print("LIVE ORDER SENT       :", result.live_order_sent)
    return 0 if result.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
