from __future__ import annotations

import os
from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import Contract, ContractDetails
from ibapi.order import Order
from ibapi.order_state import OrderState
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig, create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract_spec, to_ibapi_contract
from ai_asset_platform.brokers.ibkr_overnight_order import (
    OvernightPaperOrderSpec,
    prepare_ibkr_overnight_paper_limit_order,
)
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderSide
from ai_asset_platform.core.asset_classes import AssetClass


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
        self.contract_ready = Event()
        self.preview_ready = Event()
        self.next_order_id: int | None = None
        self.details_by_req: dict[int, list[ContractDetails]] = {}
        self.order_state: OrderState | None = None
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = orderId
        self.connected_ready.set()

    def contractDetails(self, reqId: int, contractDetails: ContractDetails) -> None:  # noqa: N802
        self.details_by_req.setdefault(reqId, []).append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.contract_ready.set()

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
            self.contract_ready.set()
            self.preview_ready.set()


def _resolve_contract_on_connected_probe(
    probe: _WhatIfProbe,
    contract: Contract,
    *,
    req_id: int,
    timeout: float,
) -> Contract | None:
    probe.contract_ready.clear()
    probe.details_by_req.pop(req_id, None)
    probe.reqContractDetails(req_id, contract)
    probe.contract_ready.wait(timeout)
    if probe.fatal_error:
        return None
    details = probe.details_by_req.get(req_id, [])
    if not details:
        return None
    return details[0].contract


def preview_ibkr_paper_overnight_order(
    *,
    symbol: str = "SPY",
    quantity: int = 1,
    limit_price: float,
    config: IbkrConnectionConfig | None = None,
    timeout: float = 10.0,
) -> IbkrOvernightWhatIfResult:
    """Resolve Overnight and request one Paper what-if preview in one TWS session.

    ContractDetails lookups and the what-if request share a single API connection.
    This avoids connection churn while keeping the what-if request single-shot.
    No real Paper order is reported as sent and Live Trading remains disabled.
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

    normalized = symbol.strip().upper()
    probe = _WhatIfProbe()
    try:
        client_id = cfg.client_id + 103
        probe.connect(cfg.host, cfg.port, client_id)
        Thread(target=probe.run, daemon=True).start()
        if not probe.connected_ready.wait(timeout) or probe.next_order_id is None:
            return IbkrOvernightWhatIfResult(
                False, False, normalized, None, None,
                quantity, float(limit_price), False, None, None, None, None,
                tuple(probe.errors),
            )
        if probe.fatal_error:
            return IbkrOvernightWhatIfResult(
                True, False, normalized, None, None,
                quantity, float(limit_price), False, None, None, None, None,
                tuple(probe.errors),
            )

        base_instrument = InstrumentSpec(
            normalized,
            AssetClass.ETF,
            exchange="SMART",
            currency="USD",
        )
        base_contract = to_ibapi_contract(build_ibkr_contract_spec(base_instrument))
        resolved_base = _resolve_contract_on_connected_probe(
            probe, base_contract, req_id=1, timeout=timeout
        )
        if resolved_base is None:
            return IbkrOvernightWhatIfResult(
                True, False, normalized, None, None,
                quantity, float(limit_price), False, None, None, None, None,
                tuple(probe.errors),
            )

        primary = (getattr(resolved_base, "primaryExchange", "") or "").strip().upper()
        if not primary:
            return IbkrOvernightWhatIfResult(
                True, False, normalized, None, None,
                quantity, float(limit_price), False, None, None, None, None,
                tuple(probe.errors),
            )

        overnight_instrument = InstrumentSpec(
            normalized,
            AssetClass.ETF,
            exchange="OVERNIGHT",
            currency="USD",
            primary_exchange=primary,
        )
        overnight_contract = to_ibapi_contract(
            build_ibkr_contract_spec(overnight_instrument)
        )
        resolved_overnight = _resolve_contract_on_connected_probe(
            probe, overnight_contract, req_id=2, timeout=timeout
        )
        if resolved_overnight is None:
            return IbkrOvernightWhatIfResult(
                True, False, normalized, primary, "OVERNIGHT",
                quantity, float(limit_price), False, None, None, None, None,
                tuple(probe.errors),
            )

        resolved_primary = (
            getattr(resolved_overnight, "primaryExchange", "") or primary
        ).strip().upper()
        prepared = prepare_ibkr_overnight_paper_limit_order(
            OvernightPaperOrderSpec(
                symbol=normalized,
                side=OrderSide.BUY,
                quantity=quantity,
                limit_price=float(limit_price),
                primary_exchange=resolved_primary,
            ),
            config=cfg,
            verified_paper_test_quantity=1,
        )
        prepared.order.whatIf = True
        prepared.order.transmit = True

        probe.placeOrder(probe.next_order_id, prepared.contract, prepared.order)
        probe.preview_ready.wait(timeout)

        state = probe.order_state
        if probe.fatal_error or state is None:
            return IbkrOvernightWhatIfResult(
                True, False, normalized, resolved_primary, "OVERNIGHT",
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
            True, True, normalized, resolved_primary, "OVERNIGHT",
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
