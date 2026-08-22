"""Broker-neutral, market-aware position sizing primitives.

This module is intentionally not wired to order transmission yet. It exists to
remove the legacy assumption that every instrument is JPY-denominated, has a
100-share lot, and has multiplier 1. A cross-currency position must provide an
explicit conversion rate into the account currency; otherwise sizing fails
closed instead of guessing an FX rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR


class MarketSizingError(ValueError):
    """Raised when safe market-aware sizing cannot be established."""


def _positive_decimal(value, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MarketSizingError(f"{name} must be numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise MarketSizingError(f"{name} must be positive")
    return parsed


def _rate(value, name: str) -> Decimal:
    parsed = _positive_decimal(value, name)
    if parsed > 1:
        raise MarketSizingError(f"{name} must be <= 1")
    return parsed


def _currency(value: str, name: str) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise MarketSizingError(f"{name} is required")
    return normalized


@dataclass(frozen=True)
class MarketSizingSpec:
    """Explicit inputs required for sizing one instrument safely.

    ``fx_to_account_rate`` means account-currency units per one unit of the
    instrument currency. Example: for a JPY account buying a USD instrument,
    1 USD = 150 JPY is represented as 150. Same-currency instruments must omit
    it (or provide 1).

    ``contract_multiplier`` is 1 for ordinary shares/ETF units. Derivatives
    must supply the broker-verified multiplier before this result can be used.
    ``quantity_increment`` and ``minimum_quantity`` are instrument-specific and
    must come from broker/product evidence rather than market-wide assumptions.
    """

    account_equity: float
    account_currency: str
    instrument_currency: str
    entry_price: float
    risk_per_trade_rate: float
    stop_loss_rate: float
    quantity_increment: float
    minimum_quantity: float
    contract_multiplier: float = 1.0
    fx_to_account_rate: float | None = None
    max_position_allocation: float = 1.0


@dataclass(frozen=True)
class MarketSizingResult:
    quantity: float
    risk_budget_account: float
    loss_per_quantity_account: float
    notional_account: float
    fx_to_account_rate: float


def resolve_fx_to_account_rate(spec: MarketSizingSpec) -> Decimal:
    account = _currency(spec.account_currency, "account_currency")
    instrument = _currency(spec.instrument_currency, "instrument_currency")
    if account == instrument:
        if spec.fx_to_account_rate is None:
            return Decimal("1")
        supplied = _positive_decimal(spec.fx_to_account_rate, "fx_to_account_rate")
        if supplied != Decimal("1"):
            raise MarketSizingError(
                "same-currency sizing requires fx_to_account_rate=1 or omission"
            )
        return supplied

    if spec.fx_to_account_rate is None:
        raise MarketSizingError(
            "cross-currency sizing requires explicit fx_to_account_rate"
        )
    return _positive_decimal(spec.fx_to_account_rate, "fx_to_account_rate")


def calculate_market_position_size(spec: MarketSizingSpec) -> MarketSizingResult:
    """Calculate quantity after risk, allocation, multiplier and step constraints.

    No price, FX conversion, lot size, increment or multiplier is inferred. A
    result of quantity 0 is a valid fail-closed sizing outcome when the risk or
    allocation budget cannot fund the broker-verified minimum quantity.
    """
    equity = _positive_decimal(spec.account_equity, "account_equity")
    entry = _positive_decimal(spec.entry_price, "entry_price")
    risk_rate = _rate(spec.risk_per_trade_rate, "risk_per_trade_rate")
    stop_rate = _rate(spec.stop_loss_rate, "stop_loss_rate")
    increment = _positive_decimal(spec.quantity_increment, "quantity_increment")
    minimum = _positive_decimal(spec.minimum_quantity, "minimum_quantity")
    multiplier = _positive_decimal(spec.contract_multiplier, "contract_multiplier")
    allocation = _rate(spec.max_position_allocation, "max_position_allocation")
    fx_rate = resolve_fx_to_account_rate(spec)

    # One unit's account-currency exposure and stop-loss loss.
    notional_per_quantity = entry * multiplier * fx_rate
    loss_per_quantity = notional_per_quantity * stop_rate
    risk_budget = equity * risk_rate
    allocation_budget = equity * allocation

    risk_quantity = risk_budget / loss_per_quantity
    allocation_quantity = allocation_budget / notional_per_quantity
    raw_quantity = min(risk_quantity, allocation_quantity)

    steps = (raw_quantity / increment).to_integral_value(rounding=ROUND_FLOOR)
    quantity = steps * increment
    if quantity < minimum:
        quantity = Decimal("0")

    notional = quantity * notional_per_quantity
    return MarketSizingResult(
        quantity=float(quantity),
        risk_budget_account=float(risk_budget),
        loss_per_quantity_account=float(loss_per_quantity),
        notional_account=float(notional),
        fx_to_account_rate=float(fx_rate),
    )
