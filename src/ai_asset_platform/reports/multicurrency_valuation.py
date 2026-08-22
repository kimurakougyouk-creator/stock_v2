"""Read-only multicurrency valuation primitives for confirmed positions.

The existing legacy Paper accounting is JPY-oriented.  This module is a pure
calculation foundation for future multi-market accounting and is deliberately
not wired to order transmission or the durable legacy ledger yet.  Every
cross-currency valuation requires an explicit conversion rate into the account
currency; no FX rate is guessed or fetched implicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


class MulticurrencyValuationError(ValueError):
    """Raised when an instrument cannot be valued without guessing."""


def _decimal(value, name: str, *, allow_zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MulticurrencyValuationError(f"{name} must be numeric") from exc
    if not parsed.is_finite():
        raise MulticurrencyValuationError(f"{name} must be finite")
    if allow_zero:
        if parsed < 0:
            raise MulticurrencyValuationError(f"{name} must be zero or positive")
    elif parsed <= 0:
        raise MulticurrencyValuationError(f"{name} must be positive")
    return parsed


def _currency(value: str, name: str) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise MulticurrencyValuationError(f"{name} is required")
    return normalized


@dataclass(frozen=True)
class PositionValuationInput:
    symbol: str
    quantity: float
    average_cost: float
    market_price: float
    instrument_currency: str
    account_currency: str
    contract_multiplier: float = 1.0
    fx_to_account_rate: float | None = None


@dataclass(frozen=True)
class PositionValuation:
    symbol: str
    quantity: float
    cost_basis_account: float
    market_value_account: float
    unrealized_pnl_account: float
    fx_to_account_rate: float


@dataclass(frozen=True)
class PortfolioValuation:
    account_currency: str
    cash_account: float
    positions_market_value_account: float
    unrealized_pnl_account: float
    total_equity_account: float
    positions: tuple[PositionValuation, ...]


def resolve_valuation_fx_rate(item: PositionValuationInput) -> Decimal:
    account = _currency(item.account_currency, "account_currency")
    instrument = _currency(item.instrument_currency, "instrument_currency")
    if account == instrument:
        if item.fx_to_account_rate is None:
            return Decimal("1")
        supplied = _decimal(item.fx_to_account_rate, "fx_to_account_rate")
        if supplied != Decimal("1"):
            raise MulticurrencyValuationError(
                "same-currency valuation requires fx_to_account_rate=1 or omission"
            )
        return supplied
    if item.fx_to_account_rate is None:
        raise MulticurrencyValuationError(
            "cross-currency valuation requires explicit fx_to_account_rate"
        )
    return _decimal(item.fx_to_account_rate, "fx_to_account_rate")


def value_position(item: PositionValuationInput) -> PositionValuation:
    symbol = str(item.symbol).strip().upper()
    if not symbol:
        raise MulticurrencyValuationError("symbol is required")
    quantity = _decimal(item.quantity, "quantity")
    average_cost = _decimal(item.average_cost, "average_cost", allow_zero=True)
    market_price = _decimal(item.market_price, "market_price", allow_zero=True)
    multiplier = _decimal(item.contract_multiplier, "contract_multiplier")
    fx_rate = resolve_valuation_fx_rate(item)

    cost_basis = quantity * average_cost * multiplier * fx_rate
    market_value = quantity * market_price * multiplier * fx_rate
    return PositionValuation(
        symbol=symbol,
        quantity=float(quantity),
        cost_basis_account=float(cost_basis),
        market_value_account=float(market_value),
        unrealized_pnl_account=float(market_value - cost_basis),
        fx_to_account_rate=float(fx_rate),
    )


def value_portfolio(
    positions: Iterable[PositionValuationInput],
    *,
    account_currency: str,
    cash_account: float,
) -> PortfolioValuation:
    account = _currency(account_currency, "account_currency")
    cash = _decimal(cash_account, "cash_account", allow_zero=True)
    valued: list[PositionValuation] = []
    for item in positions:
        item_account = _currency(item.account_currency, "account_currency")
        if item_account != account:
            raise MulticurrencyValuationError(
                "all positions must use the portfolio account currency"
            )
        valued.append(value_position(item))

    market_value = sum(Decimal(str(item.market_value_account)) for item in valued)
    unrealized = sum(Decimal(str(item.unrealized_pnl_account)) for item in valued)
    return PortfolioValuation(
        account_currency=account,
        cash_account=float(cash),
        positions_market_value_account=float(market_value),
        unrealized_pnl_account=float(unrealized),
        total_equity_account=float(cash + market_value),
        positions=tuple(valued),
    )
