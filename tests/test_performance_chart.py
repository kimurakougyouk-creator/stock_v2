from __future__ import annotations

import csv
from pathlib import Path

from ai_asset_platform.reports.performance_chart import (
    build_performance_chart_html,
)


def _write_history(path: Path) -> None:
    rows = [
        {
            "recorded_at": "2026-07-29T10:00:00",
            "net_profit": "1000",
        },
        {
            "recorded_at": "2026-07-29T11:00:00",
            "net_profit": "3000",
        },
        {
            "recorded_at": "2026-07-29T12:00:00",
            "net_profit": "4500",
        },
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "recorded_at",
                "net_profit",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_build_performance_chart_html(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "performance_history.csv"
    _write_history(history_path)

    result = build_performance_chart_html(history_path)

    assert "運用成績グラフ" in result
    assert "純損益の推移（直近3件）" in result
    assert "<svg" in result
    assert "<polyline" in result
    assert "4,500円" in result
    assert "2026-07-29T10:00:00" in result
    assert "2026-07-29T12:00:00" in result


def test_build_performance_chart_html_without_history(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "performance_history.csv"

    result = build_performance_chart_html(history_path)

    assert "運用成績グラフ" in result
    assert (
        "グラフ表示に必要な成績履歴がまだありません。"
        in result
    )


def test_build_performance_chart_html_with_one_record(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "performance_history.csv"

    with history_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "recorded_at",
                "net_profit",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "recorded_at": "2026-07-29T10:00:00",
                "net_profit": "1000",
            }
        )

    result = build_performance_chart_html(history_path)

    assert (
        "グラフ表示に必要な成績履歴がまだありません。"
        in result
    )
