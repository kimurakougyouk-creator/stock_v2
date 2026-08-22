"""Read-only accounting audit for confirmed Paper fills.

The audit consumes durable order-log records but only accepts records whose
status is explicitly FILLED. It never connects to a broker and never sends,
changes, or cancels an order. Cross-currency IBKR fills are rejected unless a
future accounting layer explicitly converts them into the account currency.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ai_asset_platform.reports.equity_history import (
    EquityPoint,
    calculate_equity_curve,
    calculate_maximum_drawdown,
)


class ConfirmedAccountingCurrencyError(ValueError):
    """Raised when confirmed monetary records cannot be combined safely."""


@dataclass(frozen=True)
class ConfirmedAccountingSummary:
    confirmed_fill_count: int
    equity_point_count: int
    ending_cash: float
    ending_holdings: float
    ending_equity: float
    realized_pnl: float
    unrealized_pnl: float
    maximum_drawdown: float


def _normalize_currency(value: str, *, field: str) -> str:
    normalized = str(value).strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ConfirmedAccountingCurrencyError(f"{field} must be a 3-letter currency code")
    return normalized


def confirmed_fill_records(records: Iterable[dict]) -> list[dict]:
    """Return only explicitly confirmed FILLED records."""
    confirmed: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("status", "")).strip().upper() != "FILLED":
            continue
        confirmed.append(record)
    return confirmed


def validate_confirmed_accounting_currency(
    records: Iterable[dict],
    *,
    account_currency: str,
) -> list[dict]:
    """Return confirmed records only when their monetary units are compatible.

    IBKR Paper records must always carry an explicit currency. If that currency
    differs from the account currency, the legacy single-currency equity engine
    cannot safely combine them, so the audit fails closed. Old local PAPER rows
    may omit currency for backward compatibility and are treated as the account
    currency; an explicit conflicting currency is still rejected.
    """
    account = _normalize_currency(account_currency, field="account_currency")
    confirmed = confirmed_fill_records(records)
    for record in confirmed:
        mode = str(record.get("mode", "")).strip().upper()
        raw_currency = str(record.get("currency", "")).strip()
        if mode == "IBKR_PAPER" and not raw_currency:
            raise ConfirmedAccountingCurrencyError(
                "IBKR_PAPER confirmed fill is missing currency"
            )
        if not raw_currency:
            continue
        currency = _normalize_currency(raw_currency, field="record currency")
        if currency != account:
            raise ConfirmedAccountingCurrencyError(
                f"confirmed fill currency {currency} cannot be combined with "
                f"account currency {account} without explicit FX conversion"
            )
    return confirmed


def load_confirmed_fill_records(path: Path) -> list[dict]:
    """Load a JSONL order log and keep only explicit FILLED records."""
    path = Path(path)
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return confirmed_fill_records(rows)


def audit_confirmed_accounting(
    records: Iterable[dict],
    *,
    initial_capital: float,
    account_currency: str = "JPY",
) -> ConfirmedAccountingSummary:
    """Rebuild PnL/equity/drawdown from compatible confirmed fills only."""
    if float(initial_capital) < 0:
        raise ValueError("initial_capital must be zero or positive")

    confirmed = validate_confirmed_accounting_currency(
        records,
        account_currency=account_currency,
    )
    points = calculate_equity_curve(confirmed, initial_capital=float(initial_capital))
    return _summary_from_points(
        confirmed_count=len(confirmed),
        points=points,
        initial_capital=float(initial_capital),
    )


def audit_confirmed_accounting_file(
    path: Path,
    *,
    initial_capital: float,
    account_currency: str = "JPY",
) -> ConfirmedAccountingSummary:
    """Convenience wrapper for a durable JSONL order log."""
    confirmed = load_confirmed_fill_records(path)
    compatible = validate_confirmed_accounting_currency(
        confirmed,
        account_currency=account_currency,
    )
    points = calculate_equity_curve(compatible, initial_capital=float(initial_capital))
    return _summary_from_points(
        confirmed_count=len(compatible),
        points=points,
        initial_capital=float(initial_capital),
    )


def _summary_from_points(
    *,
    confirmed_count: int,
    points: list[EquityPoint],
    initial_capital: float,
) -> ConfirmedAccountingSummary:
    if not points:
        return ConfirmedAccountingSummary(
            confirmed_fill_count=confirmed_count,
            equity_point_count=0,
            ending_cash=initial_capital,
            ending_holdings=0.0,
            ending_equity=initial_capital,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            maximum_drawdown=0.0,
        )

    last = points[-1]
    return ConfirmedAccountingSummary(
        confirmed_fill_count=confirmed_count,
        equity_point_count=len(points),
        ending_cash=float(last.cash),
        ending_holdings=float(last.holdings),
        ending_equity=float(last.total_assets),
        realized_pnl=float(last.realized_pnl),
        unrealized_pnl=float(last.unrealized_pnl),
        maximum_drawdown=float(calculate_maximum_drawdown(points)),
    )
