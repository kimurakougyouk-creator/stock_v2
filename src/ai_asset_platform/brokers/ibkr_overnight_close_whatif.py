"""SPY Overnight Paper SELL what-if for a position-reducing close.

The broker request uses IBKR's whatIf flag. It never creates an actual Paper or
Live position change and never retries the what-if request after connection.
"""
from __future__ import annotations

from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract_spec, to_ibapi_contract
from ai_asset_platform.brokers.ibkr_overnight_order import (
    OvernightPaperOrderSpec,
    prepare_ibkr_overnight_paper_limit_order,
)
from ai_asset_platform.brokers.ibkr_overnight_whatif import (
    IbkrOvernightWhatIfResult,
    _connect_probe_before_any_request,
    _paper_endpoint_candidates,
    _resolve_contract_on_connected_probe,
)
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderSide
from ai_asset_platform.core.asset_classes import AssetClass


def preview_spy_overnight_close_whatif(*, limit_price: float, timeout: float = 10.0) -> IbkrOvernightWhatIfResult:
    if float(limit_price) <= 0:
        raise ValueError("limit_price must be positive")
    configs = _paper_endpoint_candidates(None)
    probe, cfg, connection_errors = _connect_probe_before_any_request(
        configs, timeout=timeout, attempts_per_endpoint=2, retry_delay=1.0
    )
    if probe is None or cfg is None:
        return IbkrOvernightWhatIfResult(
            False, False, "SPY", None, None, 1, float(limit_price), False,
            None, None, None, None, connection_errors, None,
        )
    try:
        base = InstrumentSpec("SPY", AssetClass.ETF, exchange="SMART", currency="USD")
        resolved_base = _resolve_contract_on_connected_probe(
            probe, to_ibapi_contract(build_ibkr_contract_spec(base)), req_id=31, timeout=timeout
        )
        if resolved_base is None:
            return IbkrOvernightWhatIfResult(
                True, False, "SPY", None, None, 1, float(limit_price), False,
                None, None, None, None, tuple(connection_errors + tuple(probe.errors)), cfg.port,
            )
        primary = (getattr(resolved_base, "primaryExchange", "") or "").strip().upper()
        if not primary:
            return IbkrOvernightWhatIfResult(
                True, False, "SPY", None, None, 1, float(limit_price), False,
                None, None, None, None, tuple(connection_errors + tuple(probe.errors)), cfg.port,
            )
        overnight = InstrumentSpec(
            "SPY", AssetClass.ETF, exchange="OVERNIGHT", currency="USD", primary_exchange=primary
        )
        resolved = _resolve_contract_on_connected_probe(
            probe, to_ibapi_contract(build_ibkr_contract_spec(overnight)), req_id=32, timeout=timeout
        )
        if resolved is None:
            return IbkrOvernightWhatIfResult(
                True, False, "SPY", primary, "OVERNIGHT", 1, float(limit_price), False,
                None, None, None, None, tuple(connection_errors + tuple(probe.errors)), cfg.port,
            )
        resolved_primary = (getattr(resolved, "primaryExchange", "") or primary).strip().upper()
        prepared = prepare_ibkr_overnight_paper_limit_order(
            OvernightPaperOrderSpec(
                symbol="SPY", side=OrderSide.SELL, quantity=1,
                limit_price=float(limit_price), primary_exchange=resolved_primary,
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
                True, False, "SPY", resolved_primary, "OVERNIGHT", 1, float(limit_price), False,
                None, None, None, None, tuple(connection_errors + tuple(probe.errors)), cfg.port,
            )
        commission = getattr(state, "commission", None)
        try:
            commission = float(commission) if commission is not None else None
        except (TypeError, ValueError):
            commission = None
        return IbkrOvernightWhatIfResult(
            True, True, "SPY", resolved_primary, "OVERNIGHT", 1, float(limit_price), False,
            getattr(state, "maintMarginChange", None), commission,
            getattr(state, "commissionCurrency", None), getattr(state, "warningText", None),
            tuple(connection_errors + tuple(probe.errors)), cfg.port,
        )
    finally:
        if probe.isConnected():
            probe.disconnect()
