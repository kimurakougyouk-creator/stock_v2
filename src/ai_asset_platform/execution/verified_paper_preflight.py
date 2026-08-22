"""Pure fail-closed preflight for broker-verified Paper pilot orders.

This module never connects to a broker and never creates/transmits an order.
It validates one already-priced pilot order against durable confirmed fills using
one explicit account currency. Cross-currency values require an explicit FX
conversion rate supplied by the caller; no rate is guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

from ai_asset_platform.core.settings import PlatformSettings
from ai_asset_platform.reports.multicurrency_confirmed_accounting import (
    MulticurrencyConfirmedAccountingError,
    audit_multicurrency_confirmed_accounting,
)


class VerifiedPaperPreflightError(ValueError):
    """Raised when pilot risk cannot be evaluated without guessing."""


@dataclass(frozen=True)
class VerifiedPaperPreflightResult:
    allowed: bool
    reason: str
    account_currency: str
    instrument_currency: str
    fx_to_account_rate: float | None
    planned_notional_account: float | None
    daily_trading_amount_account: float | None
    ending_cash_account: float | None
    ending_holdings_account: float | None
    current_position_count: int | None
    held_quantity: int | None


def _currency(value: object, *, field: str) -> str:
    normalized = str(value or "").strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise VerifiedPaperPreflightError(f"{field} must be a 3-letter currency code")
    return normalized


def _positive_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise VerifiedPaperPreflightError(f"{field} must be numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise VerifiedPaperPreflightError(f"{field} must be positive")
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


def _record_currency(record: dict, *, account_currency: str) -> str:
    raw = str(record.get("currency", "")).strip()
    if not raw:
        if str(record.get("mode", "")).strip().upper() == "IBKR_PAPER":
            raise VerifiedPaperPreflightError("IBKR_PAPER confirmed fill is missing currency")
        return account_currency
    return _currency(raw, field="record currency")


def _record_fx(record: dict, *, fill_currency: str, account_currency: str) -> Decimal:
    raw = record.get("fx_to_account_rate")
    if fill_currency == account_currency:
        if raw in (None, ""):
            return Decimal("1")
        rate = _positive_decimal(raw, field="fx_to_account_rate")
        if rate != Decimal("1"):
            raise VerifiedPaperPreflightError(
                "same-currency fill requires fx_to_account_rate=1 or omission"
            )
        return rate
    if raw in (None, ""):
        raise VerifiedPaperPreflightError(
            f"confirmed fill currency {fill_currency} requires explicit fx_to_account_rate"
        )
    return _positive_decimal(raw, field="fx_to_account_rate")


def _deduped_accounting_records(records: Iterable[dict]) -> list[dict]:
    result: list[dict] = []
    seen_intents: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not _is_accounting_record(record):
            continue
        intent = str(record.get("order_intent_id", "")).strip()
        if intent and intent in seen_intents:
            continue
        result.append(record)
        if intent:
            seen_intents.add(intent)
    return result


def _position_quantities(records: Iterable[dict]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for index, record in enumerate(_deduped_accounting_records(records), start=1):
        ticker = str(record.get("ticker", "")).strip().upper()
        side = str(record.get("side", "")).strip().upper()
        if not ticker or side not in {"BUY", "SELL"}:
            raise VerifiedPaperPreflightError(f"accounting fill #{index} has invalid ticker/side")
        try:
            shares = int(record.get("shares"))
        except (TypeError, ValueError) as exc:
            raise VerifiedPaperPreflightError(
                f"accounting fill #{index} shares must be a whole number"
            ) from exc
        if shares <= 0:
            raise VerifiedPaperPreflightError(
                f"accounting fill #{index} shares must be positive"
            )
        held = positions.get(ticker, 0)
        if side == "BUY":
            positions[ticker] = held + shares
        else:
            if shares > held:
                raise VerifiedPaperPreflightError(
                    f"confirmed SELL for {ticker} exceeds accounted holdings"
                )
            positions[ticker] = held - shares
    return {ticker: qty for ticker, qty in positions.items() if qty > 0}


def _daily_trading_amount_account(
    records: Iterable[dict],
    *,
    target_date: date,
    account_currency: str,
) -> Decimal:
    total = Decimal("0")
    for record in _deduped_accounting_records(records):
        raw_created = record.get("created_at")
        if not raw_created:
            raise VerifiedPaperPreflightError("accounting fill is missing created_at")
        try:
            created = datetime.fromisoformat(str(raw_created))
        except (TypeError, ValueError) as exc:
            raise VerifiedPaperPreflightError("accounting fill has invalid created_at") from exc
        if created.date() != target_date:
            continue
        try:
            shares = int(record.get("shares"))
        except (TypeError, ValueError) as exc:
            raise VerifiedPaperPreflightError("accounting fill shares must be whole") from exc
        if shares <= 0:
            raise VerifiedPaperPreflightError("accounting fill shares must be positive")
        price = _positive_decimal(record.get("reference_price"), field="reference_price")
        currency = _record_currency(record, account_currency=account_currency)
        fx = _record_fx(record, fill_currency=currency, account_currency=account_currency)
        total += Decimal(shares) * price * fx
    return total


def evaluate_verified_paper_preflight(
    *,
    records: Iterable[dict],
    ticker: str,
    side: str,
    quantity: int,
    reference_price: float,
    instrument_currency: str,
    settings: PlatformSettings,
    initial_capital: float,
    fx_to_account_rate: float | None,
    stop_loss_rate: float,
    target_date: date | None = None,
) -> VerifiedPaperPreflightResult:
    """Evaluate one verified Paper pilot in account currency before transmission."""
    account_currency = _currency(settings.account_currency, field="account_currency")
    instrument = _currency(instrument_currency, field="instrument_currency")
    normalized_ticker = str(ticker).strip().upper()
    normalized_side = str(side).strip().upper()
    if not normalized_ticker:
        raise VerifiedPaperPreflightError("ticker is required")
    if normalized_side not in {"BUY", "SELL"}:
        raise VerifiedPaperPreflightError("side must be BUY or SELL")
    try:
        qty = int(quantity)
    except (TypeError, ValueError) as exc:
        raise VerifiedPaperPreflightError("quantity must be a whole number") from exc
    if qty <= 0:
        raise VerifiedPaperPreflightError("quantity must be positive")
    price = _positive_decimal(reference_price, field="reference_price")

    if instrument == account_currency:
        if fx_to_account_rate is None:
            fx = Decimal("1")
        else:
            fx = _positive_decimal(fx_to_account_rate, field="fx_to_account_rate")
            if fx != Decimal("1"):
                raise VerifiedPaperPreflightError(
                    "same-currency pilot requires fx_to_account_rate=1 or omission"
                )
    else:
        if fx_to_account_rate is None:
            raise VerifiedPaperPreflightError(
                f"{instrument}->{account_currency} preflight requires explicit FX rate"
            )
        fx = _positive_decimal(fx_to_account_rate, field="fx_to_account_rate")

    materialized = list(records)
    try:
        summary = audit_multicurrency_confirmed_accounting(
            materialized,
            initial_capital=float(initial_capital),
            account_currency=account_currency,
        )
    except MulticurrencyConfirmedAccountingError as exc:
        raise VerifiedPaperPreflightError(str(exc)) from exc

    positions = _position_quantities(materialized)
    held_quantity = int(positions.get(normalized_ticker, 0))
    position_count = len(positions)
    planned = Decimal(qty) * price * fx
    daily = _daily_trading_amount_account(
        materialized,
        target_date=target_date or date.today(),
        account_currency=account_currency,
    )

    base = dict(
        account_currency=account_currency,
        instrument_currency=instrument,
        fx_to_account_rate=float(fx),
        planned_notional_account=float(planned),
        daily_trading_amount_account=float(daily),
        ending_cash_account=float(summary.ending_cash),
        ending_holdings_account=float(summary.ending_holdings),
        current_position_count=position_count,
        held_quantity=held_quantity,
    )

    if normalized_side == "SELL":
        if held_quantity < qty:
            return VerifiedPaperPreflightResult(
                False,
                "verified Paper SELL exceeds confirmed held quantity",
                **base,
            )
        return VerifiedPaperPreflightResult(True, "protective/position-reducing SELL preflight passed", **base)

    if held_quantity > 0:
        return VerifiedPaperPreflightResult(
            False,
            "new BUY blocked because the symbol is already held",
            **base,
        )

    max_positions = int(getattr(settings, "max_positions", 0))
    if max_positions > 0 and position_count >= max_positions:
        return VerifiedPaperPreflightResult(False, "maximum position count reached", **base)

    capital = _positive_decimal(initial_capital, field="initial_capital")
    max_position_allocation = Decimal(str(max(0.0, min(1.0, float(settings.max_position_allocation)))))
    max_portfolio_allocation = Decimal(str(max(0.0, min(1.0, float(settings.max_portfolio_allocation)))))
    max_portfolio_risk_rate = Decimal(str(max(0.0, min(1.0, float(settings.max_portfolio_risk_rate)))))

    if max_position_allocation <= 0 or planned > capital * max_position_allocation:
        return VerifiedPaperPreflightResult(False, "position allocation limit would be exceeded", **base)

    projected_holdings = Decimal(str(summary.ending_holdings)) + planned
    if max_portfolio_allocation <= 0 or projected_holdings > capital * max_portfolio_allocation:
        return VerifiedPaperPreflightResult(False, "portfolio allocation limit would be exceeded", **base)

    minimum_cash_reserve = capital * (Decimal("1") - max_portfolio_allocation)
    if Decimal(str(summary.ending_cash)) - planned < minimum_cash_reserve:
        return VerifiedPaperPreflightResult(False, "minimum cash reserve would be breached", **base)

    try:
        stop_rate = Decimal(str(stop_loss_rate))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise VerifiedPaperPreflightError("stop_loss_rate must be numeric") from exc
    if not stop_rate.is_finite() or stop_rate <= 0:
        raise VerifiedPaperPreflightError("stop_loss_rate must be positive")
    projected_risk = projected_holdings * stop_rate
    if max_portfolio_risk_rate <= 0 or projected_risk > capital * max_portfolio_risk_rate:
        return VerifiedPaperPreflightResult(False, "portfolio risk limit would be exceeded", **base)

    max_daily_amount = Decimal(str(max(0.0, float(settings.max_daily_trading_amount_yen))))
    if max_daily_amount > 0 and daily + planned > max_daily_amount:
        return VerifiedPaperPreflightResult(False, "daily trading amount limit would be exceeded", **base)

    return VerifiedPaperPreflightResult(True, "verified Paper BUY preflight passed", **base)
