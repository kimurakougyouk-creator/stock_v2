"""Paper Tradingの運用成績履歴を比較する。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PerformanceTrend:
    """直近2回の運用成績の変化を表す。"""

    previous_recorded_at: str
    latest_recorded_at: str
    net_profit_change: float
    win_rate_change: float
    profit_factor_change: float
    total_trades_change: int
    status: str


def _to_float(value: object, default: float = 0.0) -> float:
    """値を安全にfloatへ変換する。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: int = 0) -> int:
    """値を安全にintへ変換する。"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _profit_factor_change(
    previous_value: object,
    latest_value: object,
) -> float:
    """プロフィットファクターの変化量を計算する。"""
    previous = _to_float(previous_value)
    latest = _to_float(latest_value)

    if previous == float("inf") and latest == float("inf"):
        return 0.0

    if latest == float("inf"):
        return float("inf")

    if previous == float("inf"):
        return float("-inf")

    return latest - previous


def _determine_status(
    *,
    net_profit_change: float,
    win_rate_change: float,
    profit_factor_change: float,
) -> str:
    """主要3指標から成績の状態を判定する。"""
    changes = [
        net_profit_change,
        win_rate_change,
        profit_factor_change,
    ]

    positive_count = sum(change > 0 for change in changes)
    negative_count = sum(change < 0 for change in changes)

    if positive_count > negative_count:
        return "improving"

    if negative_count > positive_count:
        return "declining"

    return "stable"


def read_performance_trend(
    path: Path,
) -> PerformanceTrend | None:
    """運用成績履歴CSVの直近2件を比較する。"""
    path = Path(path)

    if not path.exists():
        return None

    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            rows = list(csv.DictReader(file))
    except (OSError, csv.Error):
        return None

    if len(rows) < 2:
        return None

    previous = rows[-2]
    latest = rows[-1]

    net_profit_change = (
        _to_float(latest.get("net_profit"))
        - _to_float(previous.get("net_profit"))
    )
    win_rate_change = (
        _to_float(latest.get("win_rate"))
        - _to_float(previous.get("win_rate"))
    )
    profit_factor_change = _profit_factor_change(
        previous.get("profit_factor"),
        latest.get("profit_factor"),
    )

    return PerformanceTrend(
        previous_recorded_at=str(
            previous.get("recorded_at", "")
        ),
        latest_recorded_at=str(
            latest.get("recorded_at", "")
        ),
        net_profit_change=net_profit_change,
        win_rate_change=win_rate_change,
        profit_factor_change=profit_factor_change,
        total_trades_change=(
            _to_int(latest.get("total_trades"))
            - _to_int(previous.get("total_trades"))
        ),
        status=_determine_status(
            net_profit_change=net_profit_change,
            win_rate_change=win_rate_change,
            profit_factor_change=profit_factor_change,
        ),
    )
