"""Paper Tradingの運用成績履歴をCSVへ保存する。"""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_asset_platform.reports.performance import PerformanceSummary


PERFORMANCE_HISTORY_FIELDS = [
    "recorded_at",
    "total_trades",
    "winning_trades",
    "losing_trades",
    "break_even_trades",
    "win_rate",
    "gross_profit",
    "gross_loss",
    "net_profit",
    "average_profit",
    "average_loss",
    "largest_profit",
    "largest_loss",
    "profit_factor",
    "maximum_winning_streak",
    "maximum_losing_streak",
    "maximum_drawdown",
]

_COMPARISON_FIELDS = [field for field in PERFORMANCE_HISTORY_FIELDS if field != "recorded_at"]


def _serialize_value(value: Any) -> str:
    """CSVへ安全に保存できる文字列へ変換する。"""
    if isinstance(value, float):
        if value == float("inf"):
            return "inf"
        if value == float("-inf"):
            return "-inf"
    return str(value)


def performance_summary_to_record(
    summary: PerformanceSummary,
    *,
    recorded_at: datetime | None = None,
) -> dict[str, str]:
    """PerformanceSummaryをCSV保存用の辞書へ変換する。"""
    timestamp = recorded_at or datetime.now()
    summary_values = asdict(summary)
    record = {"recorded_at": timestamp.isoformat(timespec="seconds")}
    for field in _COMPARISON_FIELDS:
        record[field] = _serialize_value(summary_values[field])
    return record


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            return list(reader.fieldnames or []), list(reader)
    except (OSError, csv.Error):
        return [], []


def _ensure_current_schema(path: Path) -> None:
    """旧CSVを壊さず、追加列を空欄で補って現行スキーマへ移行する。"""
    fieldnames, rows = _read_rows(path)
    if not fieldnames or fieldnames == PERFORMANCE_HISTORY_FIELDS:
        return
    if not set(fieldnames).issubset(PERFORMANCE_HISTORY_FIELDS):
        raise ValueError("performance_history.csvに未知の列があるため安全に追記できません。")

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PERFORMANCE_HISTORY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in PERFORMANCE_HISTORY_FIELDS})


def _read_last_record(path: Path) -> dict[str, str] | None:
    """既存CSVの最後の有効な記録を読み込む。"""
    _, rows = _read_rows(path)
    return rows[-1] if rows else None


def _has_same_performance(first: dict[str, str], second: dict[str, str]) -> bool:
    """日時を除く運用成績が同一か判定する。"""
    return all(first.get(field, "") == second.get(field, "") for field in _COMPARISON_FIELDS)


def append_performance_history(
    summary: PerformanceSummary,
    path: Path,
    *,
    recorded_at: datetime | None = None,
) -> bool:
    """運用成績をCSVへ追記する。同一成績・取引0件は保存しない。"""
    if summary.total_trades <= 0:
        return False

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_current_schema(path)

    record = performance_summary_to_record(summary, recorded_at=recorded_at)
    last_record = _read_last_record(path)
    if last_record is not None and _has_same_performance(last_record, record):
        return False

    file_exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PERFORMANCE_HISTORY_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(record)
    return True
