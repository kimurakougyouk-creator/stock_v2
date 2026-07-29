import csv

import pytest
from pathlib import Path

from ai_asset_platform.reports.performance_trend import (
    read_performance_trend,
)


FIELDS = [
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
]


def _write_history(
    path: Path,
    rows: list[dict[str, object]],
) -> None:
    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
        )
        writer.writeheader()
        writer.writerows(rows)


def _record(
    *,
    recorded_at: str,
    total_trades: int,
    win_rate: float,
    net_profit: float,
    profit_factor: object,
) -> dict[str, object]:
    return {
        "recorded_at": recorded_at,
        "total_trades": total_trades,
        "winning_trades": 0,
        "losing_trades": 0,
        "break_even_trades": 0,
        "win_rate": win_rate,
        "gross_profit": 0,
        "gross_loss": 0,
        "net_profit": net_profit,
        "average_profit": 0,
        "average_loss": 0,
        "largest_profit": 0,
        "largest_loss": 0,
        "profit_factor": profit_factor,
        "maximum_winning_streak": 0,
        "maximum_losing_streak": 0,
    }


def test_returns_none_when_history_does_not_exist(
    tmp_path: Path,
) -> None:
    result = read_performance_trend(
        tmp_path / "missing.csv"
    )

    assert result is None


def test_returns_none_when_history_has_one_record(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.csv"
    _write_history(
        path,
        [
            _record(
                recorded_at="2026-07-29T10:00:00",
                total_trades=1,
                win_rate=100.0,
                net_profit=1000.0,
                profit_factor="inf",
            ),
        ],
    )

    assert read_performance_trend(path) is None


def test_detects_improving_performance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.csv"
    _write_history(
        path,
        [
            _record(
                recorded_at="2026-07-29T10:00:00",
                total_trades=4,
                win_rate=50.0,
                net_profit=1000.0,
                profit_factor=1.2,
            ),
            _record(
                recorded_at="2026-07-29T11:00:00",
                total_trades=6,
                win_rate=66.0,
                net_profit=2500.0,
                profit_factor=1.8,
            ),
        ],
    )

    result = read_performance_trend(path)

    assert result is not None
    assert result.net_profit_change == 1500.0
    assert result.win_rate_change == 16.0
    assert result.profit_factor_change == pytest.approx(0.6)
    assert result.total_trades_change == 2
    assert result.status == "improving"


def test_detects_declining_performance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.csv"
    _write_history(
        path,
        [
            _record(
                recorded_at="2026-07-29T10:00:00",
                total_trades=5,
                win_rate=80.0,
                net_profit=3000.0,
                profit_factor=2.0,
            ),
            _record(
                recorded_at="2026-07-29T11:00:00",
                total_trades=6,
                win_rate=50.0,
                net_profit=1000.0,
                profit_factor=1.1,
            ),
        ],
    )

    result = read_performance_trend(path)

    assert result is not None
    assert result.status == "declining"


def test_supports_infinite_profit_factor(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.csv"
    _write_history(
        path,
        [
            _record(
                recorded_at="2026-07-29T10:00:00",
                total_trades=1,
                win_rate=100.0,
                net_profit=1000.0,
                profit_factor=2.0,
            ),
            _record(
                recorded_at="2026-07-29T11:00:00",
                total_trades=2,
                win_rate=100.0,
                net_profit=2000.0,
                profit_factor="inf",
            ),
        ],
    )

    result = read_performance_trend(path)

    assert result is not None
    assert result.profit_factor_change == float("inf")
    assert result.status == "improving"
