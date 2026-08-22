"""Read-only accounting audit for confirmed Paper fills.

The audit consumes durable order-log records but only accepts records whose
status is explicitly FILLED.  It never connects to a broker and never sends,
changes, or cancels an order.
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


def confirmed_fill_records(records: Iterable[dict]) -> list[dict]:
    """Return only explicitly confirmed FILLED records.

    Missing or non-FILLED status is rejected.  This is intentionally stricter
    than the generic equity helper so READY/REJECTED/SENT diagnostic rows can
    never be mistaken for fills during production accounting.
    """
    confirmed: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("status", "")).strip().upper() != "FILLED":
            continue
        confirmed.append(record)
    return confirmed


def load_confirmed_fill_records(path: Path) -> list[dict]:
    """Load a JSONL order log and keep only explicit FILLED records.

    Malformed lines are ignored rather than guessed.  Missing files fail closed
    with an empty result because there is no confirmed evidence to account for.
    """
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
) -> ConfirmedAccountingSummary:
    """Rebuild PnL/equity/drawdown from confirmed fills only."""
    if float(initial_capital) < 0:
        raise ValueError("initial_capital must be zero or positive")

    confirmed = confirmed_fill_records(records)
    points = calculate_equity_curve(confirmed, initial_capital=float(initial_capital))
    return _summary_from_points(confirmed_count=len(confirmed), points=points, initial_capital=float(initial_capital))


def audit_confirmed_accounting_file(
    path: Path,
    *,
    initial_capital: float,
) -> ConfirmedAccountingSummary:
    """Convenience wrapper for a durable JSONL order log."""
    confirmed = load_confirmed_fill_records(path)
    points = calculate_equity_curve(confirmed, initial_capital=float(initial_capital))
    return _summary_from_points(confirmed_count=len(confirmed), points=points, initial_capital=float(initial_capital))


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
