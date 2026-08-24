"""Read-only what-if preview for the controlled 9432/TSEJ Paper close.

This module never transmits a real order. The only order request it sends to
IBKR has ``whatIf=True`` and targets exactly 100 shares of 9432/TSEJ/JPY SELL.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ai_asset_platform.brokers.ibkr_overnight_whatif import (
    _connect_probe_before_any_request,
    _paper_endpoint_candidates,
    _resolve_contract_on_connected_probe,
)
from ai_asset_platform.brokers.ibkr_paper_order_sender import (
    prepare_ibkr_paper_order_for_instrument,
)
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass

SYMBOL = "9432"
EXCHANGE = "TSEJ"
CURRENCY = "JPY"
QUANTITY = 100


@dataclass(frozen=True)
class Ibkr9432CloseWhatIfResult:
    connected: bool
    preview_received: bool
    endpoint_port: int | None
    quantity: int
    limit_price: float
    order_sent: bool = False
    warning_text: str | None = None
    commission: float | None = None
    commission_currency: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.connected and self.preview_received and not self.order_sent


def preview_9432_close_whatif(*, limit_price: float, timeout: float = 10.0) -> Ibkr9432CloseWhatIfResult:
    if float(limit_price) <= 0:
        raise ValueError("limit_price must be positive")

    probe, cfg, connection_errors = _connect_probe_before_any_request(
        _paper_endpoint_candidates(None),
        timeout=timeout,
        attempts_per_endpoint=2,
        retry_delay=1.0,
    )
    if probe is None or cfg is None:
        return Ibkr9432CloseWhatIfResult(
            False, False, None, QUANTITY, float(limit_price), False,
            errors=connection_errors,
        )

    try:
        instrument = InstrumentSpec(
            symbol=SYMBOL,
            asset_class=AssetClass.STOCK,
            exchange=EXCHANGE,
            currency=CURRENCY,
            verified_paper_test_quantity=QUANTITY,
        )
        from ai_asset_platform.brokers.ibkr_contracts import (
            build_ibkr_contract_spec,
            to_ibapi_contract,
        )

        resolved = _resolve_contract_on_connected_probe(
            probe,
            to_ibapi_contract(build_ibkr_contract_spec(instrument)),
            req_id=9432,
            timeout=timeout,
        )
        if resolved is None:
            return Ibkr9432CloseWhatIfResult(
                True, False, cfg.port, QUANTITY, float(limit_price), False,
                errors=tuple(connection_errors + tuple(probe.errors)),
            )
        resolved_exchange = str(getattr(resolved, "exchange", "") or "").strip().upper()
        if (
            str(getattr(resolved, "symbol", "")).strip().upper() != SYMBOL
            or resolved_exchange != EXCHANGE
            or str(getattr(resolved, "currency", "")).strip().upper() != CURRENCY
            or int(getattr(resolved, "conId", 0) or 0) <= 0
        ):
            return Ibkr9432CloseWhatIfResult(
                True, False, cfg.port, QUANTITY, float(limit_price), False,
                errors=tuple(connection_errors + tuple(probe.errors) + ("resolved contract identity mismatch",)),
            )

        request = OrderRequest(
            symbol=SYMBOL,
            side=OrderSide.SELL,
            quantity=QUANTITY,
            order_type=OrderType.LIMIT,
            limit_price=float(limit_price),
        )
        prepared = prepare_ibkr_paper_order_for_instrument(request, instrument, cfg)
        prepared.order.whatIf = True
        prepared.order.transmit = True
        probe.placeOrder(probe.next_order_id, prepared.contract, prepared.order)
        probe.preview_ready.wait(timeout)
        state = probe.order_state
        if probe.fatal_error or state is None:
            return Ibkr9432CloseWhatIfResult(
                True, False, cfg.port, QUANTITY, float(limit_price), False,
                errors=tuple(connection_errors + tuple(probe.errors)),
            )

        commission = getattr(state, "commission", None)
        try:
            commission_value = float(commission) if commission is not None else None
        except (TypeError, ValueError):
            commission_value = None
        return Ibkr9432CloseWhatIfResult(
            connected=True,
            preview_received=True,
            endpoint_port=cfg.port,
            quantity=QUANTITY,
            limit_price=float(limit_price),
            order_sent=False,
            warning_text=getattr(state, "warningText", None),
            commission=commission_value,
            commission_currency=getattr(state, "commissionCurrency", None),
            errors=tuple(connection_errors + tuple(probe.errors)),
        )
    finally:
        if probe.isConnected():
            probe.disconnect()
