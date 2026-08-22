"""Read-only SPY extended-hours Paper SELL what-if.

Uses SMART routing with OutsideRth=True. The request is a broker what-if only and
never changes the Paper or Live position.
"""
from __future__ import annotations

from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract_spec, to_ibapi_contract
from ai_asset_platform.brokers.ibkr_overnight_whatif import (
    IbkrOvernightWhatIfResult,
    _connect_probe_before_any_request,
    _paper_endpoint_candidates,
    _resolve_contract_on_connected_probe,
)
from ai_asset_platform.brokers.ibkr_paper_order_sender import prepare_ibkr_paper_order_for_instrument
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass


def preview_spy_extended_close_whatif(*, limit_price: float, timeout: float = 10.0) -> IbkrOvernightWhatIfResult:
    if float(limit_price) <= 0:
        raise ValueError("limit_price must be positive")

    configs = _paper_endpoint_candidates(None)
    probe, cfg, connection_errors = _connect_probe_before_any_request(
        configs, timeout=timeout, attempts_per_endpoint=2, retry_delay=1.0
    )
    if probe is None or cfg is None:
        return IbkrOvernightWhatIfResult(
            False, False, "SPY", None, "SMART", 1, float(limit_price), False,
            None, None, None, None, connection_errors, None,
        )

    try:
        instrument = InstrumentSpec(
            "SPY", AssetClass.ETF, exchange="SMART", currency="USD",
            verified_paper_test_quantity=1,
        )
        resolved = _resolve_contract_on_connected_probe(
            probe,
            to_ibapi_contract(build_ibkr_contract_spec(instrument)),
            req_id=41,
            timeout=timeout,
        )
        if resolved is None:
            return IbkrOvernightWhatIfResult(
                True, False, "SPY", None, "SMART", 1, float(limit_price), False,
                None, None, None, None, tuple(connection_errors + tuple(probe.errors)), cfg.port,
            )

        primary = (getattr(resolved, "primaryExchange", "") or "").strip().upper() or None
        request = OrderRequest(
            symbol="SPY",
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.LIMIT,
            limit_price=float(limit_price),
            outside_rth=True,
        )
        prepared = prepare_ibkr_paper_order_for_instrument(request, instrument, cfg)
        prepared.order.whatIf = True
        prepared.order.transmit = True
        probe.placeOrder(probe.next_order_id, resolved, prepared.order)
        probe.preview_ready.wait(timeout)
        state = probe.order_state
        if probe.fatal_error or state is None:
            return IbkrOvernightWhatIfResult(
                True, False, "SPY", primary, "SMART", 1, float(limit_price), False,
                None, None, None, None, tuple(connection_errors + tuple(probe.errors)), cfg.port,
            )

        commission = getattr(state, "commission", None)
        try:
            commission = float(commission) if commission is not None else None
        except (TypeError, ValueError):
            commission = None

        return IbkrOvernightWhatIfResult(
            True, True, "SPY", primary, "SMART", 1, float(limit_price), False,
            getattr(state, "maintMarginChange", None),
            commission,
            getattr(state, "commissionCurrency", None),
            getattr(state, "warningText", None),
            tuple(connection_errors + tuple(probe.errors)),
            cfg.port,
        )
    finally:
        if probe.isConnected():
            probe.disconnect()
