"""No-send order builder for the first bounded IBKR Live pilot.

This module prepares an IBKR LIMIT order only. It never opens a broker socket,
never calls ``placeOrder``, and always leaves ``transmit=False``. The builder is
intentionally narrower than the Paper builder: exact pilot scope, DAY only,
outside-RTH disabled, explicit account-currency notional evidence, and the hard
JPY ceiling shared with the operational pilot readiness gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from ibapi.contract import Contract
from ibapi.order import Order

from ai_asset_platform.brokers.ibkr_contracts import (
    build_ibkr_contract_spec,
    to_ibapi_contract,
)
from ai_asset_platform.execution.signal_order_bridge import _instrument_for_ticker
from ai_asset_platform.reports.live_operational_pilot_readiness import (
    ABSOLUTE_FIRST_PILOT_NOTIONAL_JPY,
    LIVE_PILOT_SCOPE,
)


@dataclass(frozen=True)
class LivePilotPreparedOrder:
    ticker: str
    side: str
    quantity: int
    limit_price: float
    fill_currency: str
    fx_to_jpy: float
    maximum_notional_jpy: float
    contract: Contract
    order: Order
    order_sent: bool = False
    live_order_sent: bool = False


def _positive_finite(value: object, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be positive and finite")
    return parsed


def prepare_first_live_pilot_limit_order(
    *,
    ticker: str,
    side: str,
    quantity: int,
    limit_price: float,
    fx_to_jpy: float | None,
    account_id: str,
) -> LivePilotPreparedOrder:
    """Prepare but never transmit one tightly bounded Live pilot order."""
    normalized_ticker = str(ticker or "").strip().upper()
    normalized_side = str(side or "").strip().upper()
    expected_quantity = LIVE_PILOT_SCOPE.get(normalized_ticker)
    if expected_quantity is None:
        raise ValueError("ticker is outside the exact first-Live-pilot scope")
    try:
        normalized_quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("quantity must be an integer") from exc
    if normalized_quantity != int(expected_quantity):
        raise ValueError(
            f"quantity must equal the bounded pilot quantity {expected_quantity}"
        )
    if normalized_side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")

    normalized_account = str(account_id or "").strip()
    if not normalized_account:
        raise ValueError("account_id is required ephemerally for the Live order")

    price = _positive_finite(limit_price, field="limit_price")
    instrument = _instrument_for_ticker(normalized_ticker)
    fill_currency = str(instrument.currency).strip().upper()
    if fill_currency == "JPY":
        fx = 1.0
        if fx_to_jpy not in (None, ""):
            supplied = _positive_finite(fx_to_jpy, field="fx_to_jpy")
            if supplied != 1.0:
                raise ValueError("JPY instrument requires fx_to_jpy=1 or omission")
    else:
        if fx_to_jpy in (None, ""):
            raise ValueError("non-JPY pilot requires explicit Live FX evidence")
        fx = _positive_finite(fx_to_jpy, field="fx_to_jpy")

    maximum_notional_jpy = price * float(normalized_quantity) * fx
    if maximum_notional_jpy > ABSOLUTE_FIRST_PILOT_NOTIONAL_JPY:
        raise ValueError(
            "LIMIT-price notional exceeds the absolute first-pilot JPY ceiling"
        )

    contract = to_ibapi_contract(build_ibkr_contract_spec(instrument))
    order = Order()
    order.action = normalized_side
    order.totalQuantity = normalized_quantity
    order.orderType = "LMT"
    order.lmtPrice = price
    order.tif = "DAY"
    order.outsideRth = False
    order.transmit = False
    order.account = normalized_account

    return LivePilotPreparedOrder(
        ticker=normalized_ticker,
        side=normalized_side,
        quantity=normalized_quantity,
        limit_price=price,
        fill_currency=fill_currency,
        fx_to_jpy=fx,
        maximum_notional_jpy=maximum_notional_jpy,
        contract=contract,
        order=order,
        order_sent=False,
        live_order_sent=False,
    )
