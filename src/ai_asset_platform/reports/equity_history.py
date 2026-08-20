"""Total-asset equity history for paper-trading reporting."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from ai_asset_platform.account.account import Account
from ai_asset_platform.brokers.orders import FillResult


@dataclass(frozen=True)
class EquityPoint:
    timestamp: str
    order_intent_id: str
    cash: float
    market_value: float
    total_assets: float


def calculate_equity_curve(points: Iterable[EquityPoint]) -> list[float]:
    return [float(point.total_assets) for point in points]


def calculate_maximum_drawdown(values: Iterable[float]) -> float:
    peak: float | None = None
    maximum_drawdown = 0.0
    for raw in values:
        value = float(raw)
        if peak is None or value > peak:
            peak = value
        if peak is not None:
            maximum_drawdown = max(maximum_drawdown, peak - value)
    return maximum_drawdown


def build_equity_point(
    account: Account,
    *,
    market_prices: Mapping[str, float],
    order_intent_id: str,
    timestamp: str | None = None,
) -> EquityPoint:
    if not order_intent_id.strip():
        raise ValueError("order_intent_id is required")
    summary = account.get_summary(dict(market_prices))
    return EquityPoint(
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        order_intent_id=order_intent_id,
        cash=float(summary["cash"]),
        market_value=float(summary["holdings"]),
        total_assets=float(summary["total_assets"]),
    )


def replay_fills_to_equity(
    *,
    initial_cash: float,
    fills: Iterable[tuple[str, FillResult]],
    market_prices: Mapping[str, float] | None = None,
) -> list[EquityPoint]:
    account = Account(initial_cash=initial_cash)
    points: list[EquityPoint] = []
    seen: set[str] = set()
    explicit_prices = dict(market_prices or {})
    replay_prices: dict[str, float] = {}
    for order_intent_id, fill in fills:
        if order_intent_id in seen:
            continue
        account.apply_fill(fill)
        seen.add(order_intent_id)
        replay_prices[fill.symbol] = float(fill.fill_price)
        valuation_prices = dict(replay_prices)
        valuation_prices.update(explicit_prices)
        points.append(
            build_equity_point(
                account,
                market_prices=valuation_prices,
                order_intent_id=order_intent_id,
            )
        )
    return points


_FIELDS = ["timestamp", "order_intent_id", "cash", "market_value", "total_assets"]


def load_equity_history(path: str | Path) -> list[EquityPoint]:
    target = Path(path)
    if not target.exists():
        return []
    with target.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != _FIELDS:
            raise ValueError("Unsupported equity history CSV schema")
        return [
            EquityPoint(
                timestamp=row["timestamp"],
                order_intent_id=row["order_intent_id"],
                cash=float(row["cash"]),
                market_value=float(row["market_value"]),
                total_assets=float(row["total_assets"]),
            )
            for row in reader
        ]


def append_equity_history(path: str | Path, point: EquityPoint) -> bool:
    target = Path(path)
    existing = load_equity_history(target)
    if any(item.order_intent_id == point.order_intent_id for item in existing):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    write_header = not target.exists()
    with target.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": point.timestamp,
                "order_intent_id": point.order_intent_id,
                "cash": point.cash,
                "market_value": point.market_value,
                "total_assets": point.total_assets,
            }
        )
    return True
