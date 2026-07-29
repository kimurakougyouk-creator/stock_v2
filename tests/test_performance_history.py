import csv
import json
from datetime import datetime
from pathlib import Path

from ai_asset_platform.reports import (
    append_performance_history,
    calculate_performance,
)
from dashboard import write_dashboard_html


def _read_history(
    path: Path,
) -> list[dict[str, str]]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return list(csv.DictReader(file))


def test_append_performance_history_saves_summary(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "performance_history.csv"
    summary = calculate_performance(
        [1000.0, -400.0, 600.0]
    )

    saved = append_performance_history(
        summary,
        history_path,
        recorded_at=datetime(2026, 7, 29, 15, 30, 0),
    )

    assert saved is True

    rows = _read_history(history_path)

    assert len(rows) == 1
    assert rows[0]["recorded_at"] == "2026-07-29T15:30:00"
    assert rows[0]["total_trades"] == "3"
    assert rows[0]["winning_trades"] == "2"
    assert rows[0]["losing_trades"] == "1"
    assert rows[0]["net_profit"] == "1200.0"
    assert rows[0]["profit_factor"] == "4.0"


def test_append_performance_history_skips_duplicate(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "performance_history.csv"
    summary = calculate_performance(
        [1000.0, -400.0]
    )

    first_saved = append_performance_history(
        summary,
        history_path,
        recorded_at=datetime(2026, 7, 29, 15, 30, 0),
    )
    second_saved = append_performance_history(
        summary,
        history_path,
        recorded_at=datetime(2026, 7, 29, 16, 30, 0),
    )

    assert first_saved is True
    assert second_saved is False
    assert len(_read_history(history_path)) == 1


def test_append_performance_history_skips_empty_summary(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "performance_history.csv"
    summary = calculate_performance([])

    saved = append_performance_history(
        summary,
        history_path,
    )

    assert saved is False
    assert not history_path.exists()


def test_append_performance_history_saves_changed_summary(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "performance_history.csv"

    first_summary = calculate_performance(
        [1000.0, -400.0]
    )
    second_summary = calculate_performance(
        [1000.0, -400.0, 800.0]
    )

    append_performance_history(
        first_summary,
        history_path,
    )
    saved = append_performance_history(
        second_summary,
        history_path,
    )

    assert saved is True
    assert len(_read_history(history_path)) == 2


def test_write_dashboard_saves_performance_history(
    tmp_path: Path,
) -> None:
    pnl_path = tmp_path / "paper_trade_pnls.json"
    pnl_path.write_text(
        json.dumps(
            {
                "realized_trade_pnls": [
                    1000.0,
                    -400.0,
                    600.0,
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    write_dashboard_html(tmp_path)
    write_dashboard_html(tmp_path)

    history_path = tmp_path / "performance_history.csv"

    assert history_path.exists()

    rows = _read_history(history_path)

    assert len(rows) == 1
    assert rows[0]["total_trades"] == "3"
    assert rows[0]["net_profit"] == "1200.0"
