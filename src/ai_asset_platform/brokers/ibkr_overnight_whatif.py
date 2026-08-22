from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.order_state import OrderState
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig, create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_overnight_audit import audit_ibkr_paper_overnight_contract
from ai_asset_platform.brokers.ibkr_overnight_order import (
    OvernightPaperOrderSpec,
    prepare_ibkr_overnight_paper_limit_order,
)
from ai_asset_platform.brokers.orders import OrderSide


@dataclass(frozen=True)
class IbkrOvernightWhatIfResult:
    connected: bool
    preview_received: bool
    symbol: str
    primary_exchange: str | None
    destination: str | None
    quantity: int
    limit_price: float
    order_sent: bool
    margin_change: str | None
    commission: float | None
    commission_currency: str | None
    warning_text: str | None
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.connected and self.preview_received and not self.order_sent


class _WhatIfProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.preview_ready = Event()
        self.next_order_id: int | None = None
        self.order_state: OrderState | None = None
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = orderId
        self.connected_ready.set()

    def openOrder(self, orderId: int, contract: Contract, order: Order, orderState: OrderState) -> None:  # noqa: N802
        if getattr(order, "whatIf", False):
            self.order_state = orderState
            self.preview_ready.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
        message = f"{errorCode}: {errorString}"
        self.errors.append(message)
        if errorCode in {200, 201, 203, 326, 412, 421, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.preview_ready.set()


def _resolve_overnight_contract_with_readonly_retry(
    symbol: str,
    cfg: IbkrConnectionConfig,
    *,
    timeout: float,
    attempts: int = 2,
    retry_delay: float = 1.0,
):
    """Retry only the read-only ContractDetails audit, never an order request."""
    last = None
    for attempt in range(max(1, attempts)):
        last = audit_ibkr_paper_overnight_contract(symbol, config=cfg, timeout=timeout)
        if last.overnight_contract_ready and last.primary_exchange:
            return last
        if attempt + 1 < max(1, attempts):
            time.sleep(max(0.0, retry_delay))
    return last


def preview_ibkr_paper_overnight_order(
    *,
    symbol: str = "SPY",
    quantity: int = 1,
    limit_price: float,
    config: IbkrConnectionConfig | None = None,
    timeout: float = 10.0,
) -> IbkrOvernightWhatIfResult:
    """Ask IBKR for an Overnight Paper what-if preview without placing an order.

    Only the preceding read-only ContractDetails audit may retry once. The
    what-if order request itself is attempted at most once and is never
    automatically resent.
    """
    cfg = config or create_ibkr_paper_config(use_gateway=False)
    cfg.validate()
    if cfg.port != 7497:
        raise RuntimeError("Overnight what-if preview currently requires TWS Paper port 7497.")
    if not cfg.paper_trading or cfg.allow_live_trading:
        raise RuntimeError("Overnight what-if preview requires Paper Trading with Live disabled.")
    if quantity != 1:
        raise RuntimeError("SPY Overnight what-if preview is limited to the broker-verified quantity 1.")
    if float(limit_price) <= 0:
        raise ValueError("limit_price must be positive")

    audit = _resolve_overnight_contract_with_readonly_retry(
        symbol, cfg, timeout=timeout
    )
    if audit is None or not audit.overnight_contract_ready or not audit.primary_exchange:
        message = getattr(audit, "message", "no audit result")
        raise RuntimeError(f"Overnight directed contract is not broker-resolved: {message}")

    prepared = prepare_ibkr_overnight_paper_limit_order(
        OvernightPaperOrderSpec(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            limit_price=float(limit_price),
            primary_exchange=audit.primary_exchange,
        ),
        config=cfg,
        verified_paper_test_quantity=1,
    )
    prepared.order.whatIf = True
    prepared.order.transmit = True

    probe = _WhatIfProbe()
    try:
        client_id = cfg.client_id + 103
        probe.connect(cfg.host, cfg.port, client_id)
        Thread(target=probe.run, daemon=True).start()
        if not probe.connected_ready.wait(timeout) or probe.next_order_id is None:
            return IbkrOvernightWhatIfResult(
                False, False, symbol.upper(), audit.primary_exchange, "OVERNIGHT",
                quantity, float(limit_price), False, None, None, None, None,
                tuple(probe.errors),
            )
        if probe.fatal_error:
            return IbkrOvernightWhatIfResult(
                True, False, symbol.upper(), audit.primary_exchange, "OVERNIGHT",
                quantity, float(limit_price), False, None, None, None, None,
                tuple(probe.errors),
            )

        probe.placeOrder(probe.next_order_id, prepared.contract, prepared.order)
        probe.preview_ready.wait(timeout)

        state = probe.order_state
        if probe.fatal_error or state is None:
            return IbkrOvernightWhatIfResult(
                True, False, symbol.upper(), audit.primary_exchange, "OVERNIGHT",
                quantity, float(limit_price), False, None, None, None, None,
                tuple(probe.errors),
            )

        commission = getattr(state, "commission", None)
        if commission is not None:
            try:
                commission = float(commission)
            except (TypeError, ValueError):
                commission = None

        return IbkrOvernightWhatIfResult(
            True, True, symbol.upper(), audit.primary_exchange, "OVERNIGHT",
            quantity, float(limit_price), False,
            getattr(state, "maintMarginChange", None), commission,
            getattr(state, "commissionCurrency", None),
            getattr(state, "warningText", None), tuple(probe.errors),
        )
    finally:
        if probe.isConnected():
            probe.disconnect()


def main() -> int:
    raw_price = os.getenv("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE", "").strip()
    if not raw_price:
        print("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE is required. No request was sent.")
        return 2
    try:
        price = float(raw_price)
    except ValueError:
        print("IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE must be numeric. No request was sent.")
        return 2

    result = preview_ibkr_paper_overnight_order(limit_price=price)
    print("===== IBKR PAPER OVERNIGHT WHAT-IF =====")
    print("CONNECTED          :", result.connected)
    print("PREVIEW RECEIVED   :", result.preview_received)
    print("SYMBOL             :", result.symbol)
    print("PRIMARY EXCHANGE   :", result.primary_exchange)
    print("DESTINATION        :", result.destination)
    print("QUANTITY           :", result.quantity)
    print("LIMIT PRICE        :", result.limit_price)
    print("ORDER SENT         :", result.order_sent)
    print("MARGIN CHANGE      :", result.margin_change)
    print("COMMISSION         :", result.commission)
    print("COMMISSION CURRENCY:", result.commission_currency)
    print("WARNING            :", result.warning_text)
    print("ERRORS             :", list(result.errors))
    print("OVERALL READY      :", result.ready)
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
