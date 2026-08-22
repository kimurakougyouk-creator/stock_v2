"""Fail-closed realized trade history in one explicit account currency.

This module consumes durable Paper fill records only.  It never connects to a
broker and never creates, changes, cancels, or transmits orders.  Cross-currency
fills require an explicit ``fx_to_account_rate`` captured with that fill; no FX
rate is guessed or reused from an unrelated fill.

The current path is intentionally limited to whole-share, multiplier=1 products
(stocks/ETFs).  Derivatives remain outside this accounting path until separately
verified.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable


class MulticurrencyTradeHistoryError(ValueError):
    """Raised when realized PnL cannot be reconstructed without guessing."""


@dataclass(frozen=True)
class RealizedTradeAccountCurrency:
    ticker: str
    shares: int
    average_cost_account: float
    sell_price_local: float
    sell_fx_to_account_rate: float
    sell_unit_value_account: float
    realized_pnl_account: float
    account_currency: str
    fill_currency: str
    sold_at: str | None
    order_intent_id: str | None

    def as_record(self) -> dict:
        return asdict(self)


def _currency(value: object, *, field: str) -> str:
    normalized = str(value or "").strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise MulticurrencyTradeHistoryError(f"{field} must be a 3-letter currency code")
    return normalized


def _positive_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MulticurrencyTradeHistoryError(f"{field} must be numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise MulticurrencyTradeHistoryError(f"{field} must be positive")
    return parsed


def _is_accounting_record(record: dict) -> bool:
    mode = str(record.get("mode", "")).strip().upper()
    status = str(record.get("status", "")).strip().upper()
    if mode == "IBKR_PAPER":
        return status == "FILLED"
    if mode == "PAPER":
        return status in {"", "RECORDED", "FILLED"}
    if not mode:
        return status not in {
            "READY", "READY_NOT_SENT", "SENT", "OPEN", "PENDING",
            "SUBMITTED", "PARTIALLY_FILLED", "REJECTED", "BLOCKED",
            "WAITING", "CANCELLED", "CANCELED",
        }
    return status == "FILLED"


def _fill_currency(record: dict, *, account_currency: str) -> str:
    raw = str(record.get("currency", "")).strip()
    if not raw:
        if str(record.get("mode", "")).strip().upper() == "IBKR_PAPER":
            raise MulticurrencyTradeHistoryError("IBKR_PAPER confirmed fill is missing currency")
        return account_currency
    return _currency(raw, field="record currency")


def _fx_rate(record: dict, *, fill_currency: str, account_currency: str) -> Decimal:
    raw = record.get("fx_to_account_rate")
    if fill_currency == account_currency:
        if raw in (None, ""):
            return Decimal("1")
        rate = _positive_decimal(raw, field="fx_to_account_rate")
        if rate != Decimal("1"):
            raise MulticurrencyTradeHistoryError(
                "same-currency fill requires fx_to_account_rate=1 or omission"
            )
        return rate
    if raw in (None, ""):
        raise MulticurrencyTradeHistoryError(
            f"confirmed fill currency {fill_currency} requires explicit "
            f"fx_to_account_rate into {account_currency}"
        )
    return _positive_decimal(raw, field="fx_to_account_rate")


def calculate_realized_trade_history(
    records: Iterable[dict],
    *,
    account_currency: str = "JPY",
) -> list[RealizedTradeAccountCurrency]:
    """Reconstruct each realized SELL in account currency, fail-closed.

    Average cost is maintained in account currency, so a BUY at one FX rate and
    a later SELL at another produces the correct account-currency realized PnL.
    Duplicate ``order_intent_id`` values are ignored idempotently.
    """
    account = _currency(account_currency, field="account_currency")
    quantities: dict[str, int] = {}
    average_cost_account: dict[str, Decimal] = {}
    symbol_currency: dict[str, str] = {}
    seen_intents: set[str] = set()
    realized: list[RealizedTradeAccountCurrency] = []

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict) or not _is_accounting_record(record):
            continue
        intent = str(record.get("order_intent_id", "")).strip()
        if intent and intent in seen_intents:
            continue

        ticker = str(record.get("ticker", "")).strip().upper()
        side = str(record.get("side", "")).strip().upper()
        if not ticker or side not in {"BUY", "SELL"}:
            raise MulticurrencyTradeHistoryError(
                f"accounting fill #{index} has invalid ticker/side"
            )
        try:
            shares = int(record.get("shares"))
        except (TypeError, ValueError) as exc:
            raise MulticurrencyTradeHistoryError(
                f"accounting fill #{index} shares must be a whole number"
            ) from exc
        if shares <= 0:
            raise MulticurrencyTradeHistoryError(
                f"accounting fill #{index} shares must be positive"
            )

        price = _positive_decimal(record.get("reference_price"), field="reference_price")
        fill_currency = _fill_currency(record, account_currency=account)
        rate = _fx_rate(record, fill_currency=fill_currency, account_currency=account)
        previous_currency = symbol_currency.get(ticker)
        if previous_currency is not None and previous_currency != fill_currency:
            raise MulticurrencyTradeHistoryError(
                f"symbol {ticker} changed currency from {previous_currency} to {fill_currency}"
            )
        symbol_currency[ticker] = fill_currency

        unit_account = price * rate
        held = quantities.get(ticker, 0)
        if side == "BUY":
            prior_avg = average_cost_account.get(ticker, Decimal("0"))
            new_qty = held + shares
            total_cost = prior_avg * Decimal(held) + unit_account * Decimal(shares)
            quantities[ticker] = new_qty
            average_cost_account[ticker] = total_cost / Decimal(new_qty)
        else:
            if shares > held:
                raise MulticurrencyTradeHistoryError(
                    f"confirmed SELL for {ticker} exceeds accounted holdings"
                )
            avg = average_cost_account.get(ticker)
            if avg is None:
                raise MulticurrencyTradeHistoryError(
                    f"confirmed SELL for {ticker} has no accounted cost basis"
                )
            pnl = (unit_account - avg) * Decimal(shares)
            realized.append(
                RealizedTradeAccountCurrency(
                    ticker=ticker,
                    shares=shares,
                    average_cost_account=float(avg),
                    sell_price_local=float(price),
                    sell_fx_to_account_rate=float(rate),
                    sell_unit_value_account=float(unit_account),
                    realized_pnl_account=float(pnl),
                    account_currency=account,
                    fill_currency=fill_currency,
                    sold_at=(str(record.get("created_at")) if record.get("created_at") else None),
                    order_intent_id=(intent or None),
                )
            )
            remaining = held - shares
            quantities[ticker] = remaining
            if remaining == 0:
                average_cost_account.pop(ticker, None)

        if intent:
            seen_intents.add(intent)

    return realized


def realized_pnl_for_date(
    records: Iterable[dict],
    *,
    target_date: date,
    account_currency: str = "JPY",
) -> float:
    """Return realized PnL for one local ledger date in account currency.

    A realized trade without a parseable ``sold_at`` cannot be safely assigned
    to a day and therefore fails closed.
    """
    total = Decimal("0")
    for trade in calculate_realized_trade_history(records, account_currency=account_currency):
        if not trade.sold_at:
            raise MulticurrencyTradeHistoryError("realized trade is missing sold_at")
        try:
            sold = datetime.fromisoformat(trade.sold_at)
        except (TypeError, ValueError) as exc:
            raise MulticurrencyTradeHistoryError("realized trade has invalid sold_at") from exc
        if sold.date() == target_date:
            total += Decimal(str(trade.realized_pnl_account))
    return float(total)


def consecutive_losses_account_currency(
    records: Iterable[dict],
    *,
    account_currency: str = "JPY",
) -> int:
    """Count consecutive realized losing trades from the newest backwards."""
    trades = calculate_realized_trade_history(records, account_currency=account_currency)
    count = 0
    for trade in reversed(trades):
        if trade.realized_pnl_account < 0:
            count += 1
            continue
        break
    return count
