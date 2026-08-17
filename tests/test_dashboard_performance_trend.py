from __future__ import annotations

import csv
from pathlib import Path

from dashboard import build_dashboard_html
from ai_asset_platform.reports.performance_history import (
    PERFORMANCE_HISTORY_FIELDS,
)


def _write_performance_history(path: Path) -> None:
    rows = [
        {
            "recorded_at": "2026-07-29T10:00:00",
            "total_trades": 4,
            "winning_trades": 2,
            "losing_trades": 2,
            "break_even_trades": 0,
            "win_rate": 50.0,
            "gross_profit": 3000.0,
            "gross_loss": -2000.0,
            "net_profit": 1000.0,
            "average_profit": 1500.0,
            "average_loss": -1000.0,
            "largest_profit": 2000.0,
            "largest_loss": -1200.0,
            "profit_factor": 1.5,
            "maximum_winning_streak": 1,
            "maximum_losing_streak": 1,
        },
        {
            "recorded_at": "2026-07-29T11:00:00",
            "total_trades": 6,
            "winning_trades": 4,
            "losing_trades": 2,
            "break_even_trades": 0,
            "win_rate": 66.0,
            "gross_profit": 5500.0,
            "gross_loss": -2000.0,
            "net_profit": 3500.0,
            "average_profit": 1375.0,
            "average_loss": -1000.0,
            "largest_profit": 2500.0,
            "largest_loss": -1200.0,
            "profit_factor": 2.75,
            "maximum_winning_streak": 2,
            "maximum_losing_streak": 1,
        },
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=PERFORMANCE_HISTORY_FIELDS,
        )
        writer.writeheader()
        writer.writerows(rows)


def test_dashboard_displays_performance_trend(
    tmp_path: Path,
) -> None:
    _write_performance_history(
        tmp_path / "performance_history.csv"
    )

    result = build_dashboard_html(tmp_path)

    assert "運用成績の推移" in result
    assert "総合状態" in result
    assert "改善" in result
    assert "+2,500円" in result
    assert "+16.0ポイント" in result
    assert "+1.25" in result
    assert "+2件" in result
    assert "2026-07-29T10:00:00" in result
    assert "2026-07-29T11:00:00" in result


def test_dashboard_handles_missing_performance_trend(
    tmp_path: Path,
) -> None:
    result = build_dashboard_html(tmp_path)

    assert "運用成績の推移" in result
    assert "比較できる成績履歴がまだありません。" in result
