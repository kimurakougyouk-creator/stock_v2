"""Fail-closed multi-currency accounting for confirmed whole-share fills.

This module is read-only calculation code. It never connects to a broker and
never sends, changes, or cancels orders. Cross-currency fills require an
explicit per-fill ``fx_to_account_rate`` captured for that fill; no FX rate is
guessed, fetched, or reused implicitly.

The current implementation is intentionally limited to multiplier=1 whole-share
products (stocks/ETFs). Derivatives must use a separate explicitly verified path.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

from ai_asset_platform.reports.equity_history import EquityPoint, calculate_maximum_drawdown


class MulticurrencyConfirmedAccountingError(ValueError):
    """Raised when confirmed fills cannot be accounted without guessing."""


@dataclass(frozen=True)
class MulticurrencyConfirmedAccountingSummary:
    account_currency: str
    confirmed_fill_count: int
    equity_point_count: int
    ending_cash: float
    ending_holdings: float
    ending_equity: float
    realized_pnl: float
    unrealized_pnl: float
    maximum_drawdown: float


def _currency(value: object, *, field: str) -> str:
    normalized = str(value or "").strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise MulticurrencyConfirmedAccountingError(
            f"{field} must be a 3-letter currency code"
        )
    return normalized


def _positive_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MulticurrencyConfirmedAccountingError(f"{field} must be numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise MulticurrencyConfirmedAccountingError(f"{field} must be positive")
    return parsed


def _fill_currency(record: dict, account_currency: str) -> str:
    raw = str(record.get("currency", "")).strip()
    mode = str(record.get("mode", "")).strip().upper()
    if not raw:
        if mode == "IBKR_PAPER":
            raise MulticurrencyConfirmedAccountingError(
                "IBKR_PAPER confirmed fill is missing currency"
            )
        return account_currency
    return _currency(raw, field="record currency")


def _fx_rate(record: dict, *, fill_currency: str, account_currency: str) -> Decimal:
    raw = record.get("fx_to_account_rate")
    if fill_currency == account_currency:
        if raw in (None, ""):
            return Decimal("1")
        rate = _positive_decimal(raw, field="fx_to_account_rate")
        if rate != Decimal("1"):
            raise MulticurrencyConfirmedAccountingError(
                "same-currency fill requires fx_to_account_rate=1 or omission"
            )
        return rate
    if raw in (None, ""):
        raise MulticurrencyConfirmedAccountingError(
            f"confirmed fill currency {fill_currency} requires explicit "
            f"fx_to_account_rate into {account_currency}"
        )
    return _positive_decimal(raw, field="fx_to_account_rate")


def calculate_multicurrency_equity_curve(
    records: Iterable[dict],
    *,
    initial_capital: float,
    account_currency: str = "JPY",
) -> list[EquityPoint]:
    """Rebuild account-currency equity from explicit-FX confirmed fills only.

    Each cross-currency fill must carry the conversion rate effective for that
    fill. At every fill event, positions in that currency are marked using the
    latest explicit rate observed for that currency and their latest fill price.
    """
    account = _currency(account_currency, field="account_currency")
    try:
        initial = Decimal(str(initial_capital))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MulticurrencyConfirmedAccountingError(
            "initial_capital must be numeric"
        ) from exc
    if not initial.is_finite() or initial < 0:
        raise MulticurrencyConfirmedAccountingError(
            "initial_capital must be zero or positive"
        )

    cash = initial
    quantities: dict[str, int] = {}
    average_cost_account: dict[str, Decimal] = {}
    last_local_price: dict[str, Decimal] = {}
    symbol_currency: dict[str, str] = {}
    latest_fx: dict[str, Decimal] = {account: Decimal("1")}
    realized = Decimal("0")
    points: list[EquityPoint] = []
    seen_intents: set[str] = set()
    confirmed_count = 0

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            continue
        if str(record.get("status", "")).strip().upper() != "FILLED":
            continue

        intent = str(record.get("order_intent_id", "")).strip()
        if intent and intent in seen_intents:
            continue

        symbol = str(record.get("ticker", "")).strip().upper()
        side = str(record.get("side", "")).strip().upper()
        if not symbol or side not in {"BUY", "SELL"}:
            raise MulticurrencyConfirmedAccountingError(
                f"confirmed fill #{index} has invalid ticker/side"
            )
        try:
            shares = int(record.get("shares"))
        except (TypeError, ValueError) as exc:
            raise MulticurrencyConfirmedAccountingError(
                f"confirmed fill #{index} shares must be a whole number"
            ) from exc
        if shares <= 0:
            raise MulticurrencyConfirmedAccountingError(
                f"confirmed fill #{index} shares must be positive"
            )

        price = _positive_decimal(record.get("reference_price"), field="reference_price")
        fill_currency = _fill_currency(record, account)
        rate = _fx_rate(
            record,
            fill_currency=fill_currency,
            account_currency=account,
        )

        previous_currency = symbol_currency.get(symbol)
        if previous_currency is not None and previous_currency != fill_currency:
            raise MulticurrencyConfirmedAccountingError(
                f"symbol {symbol} changed currency from {previous_currency} to {fill_currency}"
            )
        symbol_currency[symbol] = fill_currency
        latest_fx[fill_currency] = rate
        last_local_price[symbol] = price

        held = quantities.get(symbol, 0)
        unit_cost_account = price * rate
        if side == "BUY":
            previous_avg = average_cost_account.get(symbol, Decimal("0"))
            new_qty = held + shares
            total_cost = previous_avg * Decimal(held) + unit_cost_account * Decimal(shares)
            quantities[symbol] = new_qty
            average_cost_account[symbol] = total_cost / Decimal(new_qty)
            cash -= unit_cost_account * Decimal(shares)
        else:
            if shares > held:
                raise MulticurrencyConfirmedAccountingError(
                    f"confirmed SELL for {symbol} exceeds accounted holdings"
                )
            avg = average_cost_account.get(symbol)
            if avg is None:
                raise MulticurrencyConfirmedAccountingError(
                    f"confirmed SELL for {symbol} has no accounted cost basis"
                )
            proceeds = unit_cost_account * Decimal(shares)
            cash += proceeds
            realized += (unit_cost_account - avg) * Decimal(shares)
            remaining = held - shares
            quantities[symbol] = remaining
            if remaining == 0:
                average_cost_account.pop(symbol, None)

        holdings = Decimal("0")
        unrealized = Decimal("0")
        for held_symbol, held_qty in quantities.items():
            if held_qty <= 0:
                continue
            currency = symbol_currency[held_symbol]
            fx = latest_fx.get(currency)
            local_mark = last_local_price.get(held_symbol)
            avg = average_cost_account.get(held_symbol)
            if fx is None or local_mark is None or avg is None:
                raise MulticurrencyConfirmedAccountingError(
                    f"cannot value open position {held_symbol} without explicit FX/price/cost"
                )
            market_unit_account = local_mark * fx
            market_value = market_unit_account * Decimal(held_qty)
            holdings += market_value
            unrealized += (market_unit_account - avg) * Decimal(held_qty)

        total_assets = cash + holdings
        points.append(
            EquityPoint(
                recorded_at=str(record.get("created_at") or f"fill-{index}"),
                cash=float(cash),
                holdings=float(holdings),
                total_assets=float(total_assets),
                realized_pnl=float(realized),
                unrealized_pnl=float(unrealized),
            )
        )
        confirmed_count += 1
        if intent:
            seen_intents.add(intent)

    return points


def audit_multicurrency_confirmed_accounting(
    records: Iterable[dict],
    *,
    initial_capital: float,
    account_currency: str = "JPY",
) -> MulticurrencyConfirmedAccountingSummary:
    """Return a fail-closed account-currency summary from confirmed fills."""
    materialized = list(records)
    points = calculate_multicurrency_equity_curve(
        materialized,
        initial_capital=initial_capital,
        account_currency=account_currency,
    )
    confirmed_count = len(points)
    if not points:
        return MulticurrencyConfirmedAccountingSummary(
            account_currency=_currency(account_currency, field="account_currency"),
            confirmed_fill_count=0,
            equity_point_count=0,
            ending_cash=float(initial_capital),
            ending_holdings=0.0,
            ending_equity=float(initial_capital),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            maximum_drawdown=0.0,
        )
    last = points[-1]
    return MulticurrencyConfirmedAccountingSummary(
        account_currency=_currency(account_currency, field="account_currency"),
        confirmed_fill_count=confirmed_count,
        equity_point_count=len(points),
        ending_cash=float(last.cash),
        ending_holdings=float(last.holdings),
        ending_equity=float(last.total_assets),
        realized_pnl=float(last.realized_pnl),
        unrealized_pnl=float(last.unrealized_pnl),
        maximum_drawdown=float(calculate_maximum_drawdown(points)),
    )
