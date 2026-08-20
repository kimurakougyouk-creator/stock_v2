"""確定済み約定(Paper/IBKR Paper)から総資産(Equity)時系列を再構築する。

paper_orders.jsonl に記録された確定約定を、既存の Account.apply_fill /
Portfolio.apply_fill へ発生順に再生することで、cash・保有評価額・実現損益を
新規ロジックを増やさずに求める。保有中銘柄の評価には、その銘柄の直近約定価格
(mark-to-last-trade)を使う。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ai_asset_platform.account import Account
from ai_asset_platform.brokers.orders import FillResult, OrderSide

EQUITY_HISTORY_FIELDS = [
    "recorded_at", "cash", "holdings", "total_assets", "realized_pnl", "unrealized_pnl"
]

@dataclass(frozen=True)
class EquityPoint:
    recorded_at: str
    cash: float
    holdings: float
    total_assets: float
    realized_pnl: float
    unrealized_pnl: float


def _order_to_fill(order: dict, index: int) -> FillResult | None:
    try:
        ticker = str(order["ticker"]).strip()
        side = OrderSide(str(order["side"]).upper())
        shares = int(order["shares"])
        price = float(order["reference_price"])
    except (KeyError, TypeError, ValueError):
        return None
    if not ticker or shares <= 0 or price <= 0:
        return None
    order_id = str(order.get("order_intent_id") or order.get("order_id") or f"legacy-{index}")
    return FillResult(order_id=order_id, symbol=ticker, side=side, quantity=shares, fill_price=price)


def calculate_equity_curve(orders: Iterable[dict], *, initial_capital: float) -> list[EquityPoint]:
    """確定約定をAccountへ再生し、各約定後の総資産を返す。"""
    account = Account(initial_cash=float(initial_capital))
    points: list[EquityPoint] = []
    last_prices: dict[str, float] = {}
    seen_intents: set[str] = set()
    for index, order in enumerate(orders, start=1):
        if not isinstance(order, dict):
            continue
        intent = str(order.get("order_intent_id") or "").strip()
        if intent and intent in seen_intents:
            continue
        fill = _order_to_fill(order, index)
        if fill is None:
            continue
        try:
            account.apply_fill(fill)
        except ValueError:
            continue
        if intent:
            seen_intents.add(intent)
        last_prices[fill.symbol] = float(fill.fill_price)
        summary = account.get_summary(last_prices)
        points.append(EquityPoint(
            recorded_at=str(order.get("created_at") or datetime.now().isoformat(timespec="seconds")),
            cash=float(summary["cash"]),
            holdings=float(summary["holdings"]),
            total_assets=float(summary["total_assets"]),
            realized_pnl=float(summary["realized_pnl"]),
            unrealized_pnl=float(summary["unrealized_pnl"]),
        ))
    return points


def calculate_maximum_drawdown(points: Iterable[EquityPoint]) -> float:
    """総資産ピークからの最大下落額を返す。"""
    peak: float | None = None
    maximum = 0.0
    for point in points:
        value = float(point.total_assets)
        peak = value if peak is None else max(peak, value)
        maximum = max(maximum, peak - value)
    return maximum


def equity_point_to_record(point: EquityPoint) -> dict[str, str]:
    return {field: str(getattr(point, field)) for field in EQUITY_HISTORY_FIELDS}


def _read_last_record(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
    except (OSError, csv.Error):
        return None
    return rows[-1] if rows else None


def append_equity_history(point: EquityPoint, path: Path) -> bool:
    """総資産履歴をCSVへ冪等追記する。同じ状態の連続保存は行わない。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = equity_point_to_record(point)
    last = _read_last_record(path)
    comparison = [field for field in EQUITY_HISTORY_FIELDS if field != "recorded_at"]
    if last is not None and all(last.get(field, "") == record[field] for field in comparison):
        return False
    file_exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=EQUITY_HISTORY_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)
    return True
