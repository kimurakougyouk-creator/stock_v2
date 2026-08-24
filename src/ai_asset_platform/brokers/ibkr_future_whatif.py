"""Paper-only IBKR futures What-If preview for one explicit contract.

This module is intentionally fail-closed: it requires an exact broker-resolved
FUT contract and submits only a single whatIf=True order to IBKR Paper. It does
not expose a real-order mode and never enables Live Trading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from threading import Event

from ibapi.client import EClient
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_future_contracts import VerifiedFutureContractInput, build_verified_future_contract
from ai_asset_platform.brokers.ibkr_probe_thread import start_guarded_ibapi_loop


@dataclass(frozen=True)
class IbkrFutureWhatIfResult:
    connected: bool
    endpoint_port: int | None
    preview_received: bool
    order_id: int | None
    margin_change: str | None = None
    commission: str | None = None
    commission_currency: str | None = None
    warning: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    real_order_sent: bool = False
    live_order_sent: bool = False


class _FutureWhatIfProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.preview_ready = Event()
        self.next_order_id: int | None = None
        self.margin_change: str | None = None
        self.commission: str | None = None
        self.commission_currency: str | None = None
        self.warning: str | None = None
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = int(orderId)
        self.connected_ready.set()

    def openOrder(self, orderId, contract, order, orderState):  # noqa: N802
        if int(orderId) != int(self.next_order_id or -1):
            return
        self.margin_change = str(getattr(orderState, "initMarginChange", "") or "") or None
        commission = getattr(orderState, "commission", None)
        if commission is not None:
            self.commission = str(commission)
        self.commission_currency = str(getattr(orderState, "commissionCurrency", "") or "") or None
        self.warning = str(getattr(orderState, "warningText", "") or "") or None
        self.preview_ready.set()

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):  # noqa: N802,E501
        if int(orderId) == int(self.next_order_id or -1) and str(status).upper() in {"INACTIVE", "PRESUBMITTED", "SUBMITTED"}:
            self.preview_ready.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
        message = f"{errorCode}: {errorString}"
        self.errors.append(message)
        if int(errorCode) in {201, 202, 321, 322, 323, 326, 502, 503, 504, 1100}:
            self.preview_ready.set()
            if int(errorCode) in {502, 503, 504, 1100}:
                self.connected_ready.set()


def _positive_integral_quantity(value: int | float | str) -> int:
    parsed = Decimal(str(value))
    if parsed <= 0 or parsed != parsed.to_integral_value():
        raise ValueError("futures quantity must be a positive integer")
    return int(parsed)


def _positive_price(value: int | float | str) -> float:
    parsed = Decimal(str(value))
    if parsed <= 0:
        raise ValueError("futures limit price must be positive")
    return float(parsed)


def preview_ibkr_paper_future_whatif(
    *,
    symbol: str,
    exchange: str,
    currency: str,
    expiry: str,
    multiplier: str,
    local_symbol: str,
    con_id: int,
    side: str,
    quantity: int,
    limit_price: float,
    timeout: float = 10.0,
) -> IbkrFutureWhatIfResult:
    side = str(side).strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("futures side must be BUY or SELL")
    quantity = _positive_integral_quantity(quantity)
    limit_price = _positive_price(limit_price)
    spec = VerifiedFutureContractInput(
        symbol=symbol,
        exchange=exchange,
        currency=currency,
        expiry=expiry,
        multiplier=multiplier,
        local_symbol=local_symbol,
        con_id=int(con_id),
    )
    contract = build_verified_future_contract(spec)
    if not contract.localSymbol or int(contract.conId or 0) <= 0:
        raise ValueError("explicit broker-resolved futures localSymbol and conId are required")

    cfg = create_ibkr_paper_config(use_gateway=True)
    probe = _FutureWhatIfProbe()
    try:
        probe.connect(cfg.host, cfg.port, cfg.client_id + 260)
        start_guarded_ibapi_loop(probe.run, name="ibkr-future-whatif")
        if not probe.connected_ready.wait(timeout) or probe.next_order_id is None:
            return IbkrFutureWhatIfResult(
                connected=False,
                endpoint_port=cfg.port,
                preview_received=False,
                order_id=None,
                errors=tuple(probe.errors),
            )

        order = Order()
        order.action = side
        order.orderType = "LMT"
        order.totalQuantity = quantity
        order.lmtPrice = limit_price
        order.tif = "DAY"
        order.whatIf = True
        order.transmit = True
        order.orderRef = "stock_v2-future-whatif"
        probe.placeOrder(probe.next_order_id, contract, order)
        probe.preview_ready.wait(timeout)
        return IbkrFutureWhatIfResult(
            connected=True,
            endpoint_port=cfg.port,
            preview_received=probe.preview_ready.is_set(),
            order_id=probe.next_order_id,
            margin_change=probe.margin_change,
            commission=probe.commission,
            commission_currency=probe.commission_currency,
            warning=probe.warning,
            errors=tuple(probe.errors),
            real_order_sent=False,
            live_order_sent=False,
        )
    finally:
        if probe.isConnected():
            probe.disconnect()
