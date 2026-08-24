"""Explicit, Paper-only IBKR FX what-if preview.

This module may submit exactly one IBKR ``whatIf=True`` order preview after a
read-only ContractDetails discovery. It never exposes a real-order mode, never
enables Live Trading, never retries the what-if request, and never promotes FX
to VERIFIED_CAPABILITIES.

All economically meaningful fields are caller-supplied: pair, exchange, side,
quantity mode, quantity, and limit price. The current broker-preview path is
intentionally narrower than the pure intent model: only TOTAL_QUANTITY with an
integral quantity is accepted. CASH_QUANTITY remains blocked until its sizing
and accounting semantics are independently verified.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from threading import Event

from ibapi.client import EClient
from ibapi.order import Order
from ibapi.order_state import OrderState
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_fx_contracts import (
    contract_input_from_discovery_candidate,
    build_verified_fx_contract,
)
from ai_asset_platform.brokers.ibkr_fx_discovery import (
    IbkrFxCandidate,
    discover_ibkr_paper_fx,
)
from ai_asset_platform.brokers.ibkr_fx_whatif_intent import (
    FxQuantityMode,
    FxWhatIfIntentInput,
    verify_fx_whatif_intent,
)
from ai_asset_platform.brokers.ibkr_probe_thread import start_guarded_ibapi_loop
from ai_asset_platform.brokers.orders import OrderSide


PAPER_API_PORTS = {4002, 7497}


@dataclass(frozen=True)
class IbkrFxWhatIfResult:
    connected: bool
    discovery_resolved: bool
    preview_received: bool
    base_currency: str
    quote_currency: str
    exchange: str
    side: str
    quantity_mode: str
    quantity: float
    limit_price: float
    con_id: int | None
    endpoint_port: int | None
    whatif_submitted: bool
    real_order_sent: bool = False
    margin_change: str | None = None
    commission: float | None = None
    commission_currency: str | None = None
    warning_text: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.connected
            and self.discovery_resolved
            and self.preview_received
            and self.whatif_submitted
            and not self.real_order_sent
        )


class _FxWhatIfProbe(EWrapper, EClient):
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
        self.next_order_id = int(orderId)
        self.connected_ready.set()

    def openOrder(self, orderId, contract, order, orderState) -> None:  # noqa: N802
        if bool(getattr(order, "whatIf", False)):
            self.order_state = orderState
            self.preview_ready.set()

    def error(self, reqId, *args):
        # Support both older and newer ibapi callback signatures.
        if len(args) >= 3:
            error_code, error_string = args[-3], args[-2]
        elif len(args) >= 2:
            error_code, error_string = args[0], args[1]
        else:
            return
        try:
            code = int(error_code)
        except (TypeError, ValueError):
            return
        message = f"{code}: {error_string}"
        self.errors.append(message)
        if code in {200, 201, 203, 326, 412, 421, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.preview_ready.set()


def _exact_candidate(candidates: tuple[IbkrFxCandidate, ...]) -> IbkrFxCandidate:
    usable = [
        item
        for item in candidates
        if item.con_id is not None and int(item.con_id) > 0
    ]
    if len(usable) != 1:
        raise RuntimeError(
            f"FX what-if requires exactly one broker candidate with positive conId; found {len(usable)}"
        )
    return usable[0]


def _build_total_quantity_whatif_order(*, intent) -> Order:
    if intent.quantity_mode is not FxQuantityMode.TOTAL_QUANTITY:
        raise RuntimeError(
            "FX broker what-if currently supports TOTAL_QUANTITY only; CASH_QUANTITY remains blocked"
        )
    quantity: Decimal = intent.quantity
    if quantity != quantity.to_integral_value():
        raise RuntimeError("FX TOTAL_QUANTITY what-if currently requires an integral quantity")

    order = Order()
    order.action = intent.side.value
    order.orderType = "LMT"
    order.totalQuantity = int(quantity)
    order.lmtPrice = float(intent.limit_price)
    order.tif = "DAY"
    order.outsideRth = False
    order.whatIf = True
    # IBKR what-if previews are submitted through placeOrder with whatIf=True.
    # transmit=True is required for preview evaluation; whatIf=True prevents a
    # real order from being transmitted to the market.
    order.transmit = True
    order.orderRef = "stock_v2-fx-whatif"
    return order


def preview_ibkr_paper_fx_whatif(
    *,
    base_currency: str,
    quote_currency: str,
    exchange: str,
    side: OrderSide,
    quantity_mode: FxQuantityMode,
    quantity: float,
    limit_price: float,
    timeout: float = 10.0,
) -> IbkrFxWhatIfResult:
    """Submit one FX Paper what-if preview, never a real order."""
    base = str(base_currency).strip().upper()
    quote = str(quote_currency).strip().upper()
    venue = str(exchange).strip().upper()

    discovery = discover_ibkr_paper_fx(
        base_currency=base,
        quote_currency=quote,
        exchange=venue,
        timeout=timeout,
    )
    if not discovery.resolved:
        return IbkrFxWhatIfResult(
            connected=discovery.connected,
            discovery_resolved=False,
            preview_received=False,
            base_currency=base,
            quote_currency=quote,
            exchange=venue,
            side=getattr(side, "value", str(side)),
            quantity_mode=getattr(quantity_mode, "value", str(quantity_mode)),
            quantity=float(quantity),
            limit_price=float(limit_price),
            con_id=None,
            endpoint_port=discovery.endpoint_port,
            whatif_submitted=False,
            errors=tuple(discovery.errors),
        )

    try:
        candidate = _exact_candidate(discovery.candidates)
        contract_input = contract_input_from_discovery_candidate(candidate)
        intent = verify_fx_whatif_intent(
            FxWhatIfIntentInput(
                base_currency=contract_input.base_currency,
                quote_currency=contract_input.quote_currency,
                exchange=contract_input.exchange,
                con_id=int(contract_input.con_id or 0),
                local_symbol=contract_input.local_symbol,
                side=side,
                quantity_mode=quantity_mode,
                quantity=quantity,
                limit_price=limit_price,
                min_size=candidate.min_size,
                size_increment=candidate.size_increment,
            )
        )
        order = _build_total_quantity_whatif_order(intent=intent)
        contract = build_verified_fx_contract(intent.contract_input)
    except (TypeError, ValueError, RuntimeError) as exc:
        return IbkrFxWhatIfResult(
            connected=discovery.connected,
            discovery_resolved=True,
            preview_received=False,
            base_currency=base,
            quote_currency=quote,
            exchange=venue,
            side=getattr(side, "value", str(side)),
            quantity_mode=getattr(quantity_mode, "value", str(quantity_mode)),
            quantity=float(quantity),
            limit_price=float(limit_price),
            con_id=(discovery.candidates[0].con_id if discovery.candidates else None),
            endpoint_port=discovery.endpoint_port,
            whatif_submitted=False,
            errors=tuple(discovery.errors) + (str(exc),),
        )

    if discovery.endpoint_port not in PAPER_API_PORTS:
        return IbkrFxWhatIfResult(
            connected=False,
            discovery_resolved=True,
            preview_received=False,
            base_currency=base,
            quote_currency=quote,
            exchange=venue,
            side=side.value,
            quantity_mode=quantity_mode.value,
            quantity=float(intent.quantity),
            limit_price=float(intent.limit_price),
            con_id=int(intent.contract_input.con_id or 0),
            endpoint_port=discovery.endpoint_port,
            whatif_submitted=False,
            errors=tuple(discovery.errors) + ("FX discovery did not use a Paper endpoint",),
        )

    cfg = create_ibkr_paper_config(use_gateway=discovery.endpoint_port == 4002)
    cfg.validate()
    if not cfg.paper_trading or cfg.allow_live_trading or cfg.port != discovery.endpoint_port:
        raise RuntimeError("FX what-if requires the exact discovered Paper endpoint with Live disabled")

    probe = _FxWhatIfProbe()
    submitted = False
    thread = None
    thread_state = None
    try:
        try:
            probe.connect(cfg.host, cfg.port, cfg.client_id + 241)
        except OSError as exc:
            return IbkrFxWhatIfResult(
                False, True, False, base, quote, venue, side.value,
                quantity_mode.value, float(intent.quantity), float(intent.limit_price),
                int(intent.contract_input.con_id or 0), cfg.port, False,
                errors=tuple(discovery.errors) + (str(exc),),
            )
        thread, thread_state = start_guarded_ibapi_loop(
            probe.run, name=f"ibkr-fx-whatif-{cfg.port}"
        )
        if not probe.connected_ready.wait(timeout) or probe.next_order_id is None or probe.fatal_error:
            errors = list(discovery.errors) + list(probe.errors)
            if thread_state.exception:
                errors.append(f"message-loop {thread_state.exception}")
            return IbkrFxWhatIfResult(
                False, True, False, base, quote, venue, side.value,
                quantity_mode.value, float(intent.quantity), float(intent.limit_price),
                int(intent.contract_input.con_id or 0), cfg.port, False,
                errors=tuple(errors),
            )

        # Exactly one what-if request. There is deliberately no retry path after
        # this point, even on timeout or uncertain preview state.
        probe.placeOrder(probe.next_order_id, contract, order)
        submitted = True
        probe.preview_ready.wait(timeout)
        state = probe.order_state
        errors = list(discovery.errors) + list(probe.errors)
        if thread_state.exception:
            errors.append(f"message-loop {thread_state.exception}")
        if probe.fatal_error or state is None:
            return IbkrFxWhatIfResult(
                True, True, False, base, quote, venue, side.value,
                quantity_mode.value, float(intent.quantity), float(intent.limit_price),
                int(intent.contract_input.con_id or 0), cfg.port, submitted,
                errors=tuple(errors),
            )

        commission_raw = getattr(state, "commission", None)
        try:
            commission = float(commission_raw) if commission_raw is not None else None
        except (TypeError, ValueError):
            commission = None
        return IbkrFxWhatIfResult(
            connected=True,
            discovery_resolved=True,
            preview_received=True,
            base_currency=base,
            quote_currency=quote,
            exchange=venue,
            side=side.value,
            quantity_mode=quantity_mode.value,
            quantity=float(intent.quantity),
            limit_price=float(intent.limit_price),
            con_id=int(intent.contract_input.con_id or 0),
            endpoint_port=cfg.port,
            whatif_submitted=True,
            real_order_sent=False,
            margin_change=getattr(state, "maintMarginChange", None),
            commission=commission,
            commission_currency=getattr(state, "commissionCurrency", None),
            warning_text=getattr(state, "warningText", None),
            errors=tuple(errors),
        )
    finally:
        if probe.isConnected():
            probe.disconnect()
        if thread is not None:
            thread.join(timeout=1.0)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required; FX what-if inputs are never inferred")
    return value


def main() -> int:
    try:
        side = OrderSide(_required_env("IBKR_FX_WHATIF_SIDE").upper())
        mode = FxQuantityMode(_required_env("IBKR_FX_WHATIF_QUANTITY_MODE").upper())
        result = preview_ibkr_paper_fx_whatif(
            base_currency=_required_env("IBKR_FX_WHATIF_BASE"),
            quote_currency=_required_env("IBKR_FX_WHATIF_QUOTE"),
            exchange=_required_env("IBKR_FX_WHATIF_EXCHANGE"),
            side=side,
            quantity_mode=mode,
            quantity=float(_required_env("IBKR_FX_WHATIF_QUANTITY")),
            limit_price=float(_required_env("IBKR_FX_WHATIF_LIMIT_PRICE")),
        )
    except (RuntimeError, ValueError) as exc:
        print("===== IBKR PAPER FX WHAT-IF =====")
        print("READY                 : False")
        print("ERROR                 :", exc)
        print("REAL ORDER SENT       : False")
        print("LIVE ORDER SENT       : False")
        return 2

    print("===== IBKR PAPER FX WHAT-IF =====")
    print("CONNECTED             :", result.connected)
    print("DISCOVERY RESOLVED    :", result.discovery_resolved)
    print("PREVIEW RECEIVED      :", result.preview_received)
    print("PAIR                  :", f"{result.base_currency}/{result.quote_currency}")
    print("EXCHANGE              :", result.exchange)
    print("SIDE                  :", result.side)
    print("QUANTITY MODE         :", result.quantity_mode)
    print("QUANTITY              :", result.quantity)
    print("LIMIT PRICE           :", result.limit_price)
    print("CON ID                :", result.con_id)
    print("ENDPOINT PORT         :", result.endpoint_port)
    print("WHATIF SUBMITTED      :", result.whatif_submitted)
    print("MARGIN CHANGE         :", result.margin_change)
    print("COMMISSION            :", result.commission)
    print("COMMISSION CURRENCY   :", result.commission_currency)
    print("WARNING               :", result.warning_text)
    print("ERRORS                :", list(result.errors))
    print("READY                 :", result.ready)
    print("REAL ORDER SENT       : False")
    print("LIVE ORDER SENT       : False")
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
