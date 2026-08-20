import csv
import json
from datetime import datetime
from pathlib import Path

from ai_asset_platform.reports import append_performance_history, calculate_performance
from dashboard import write_dashboard_html


def _read_history(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def test_append_performance_history_saves_summary(tmp_path: Path) -> None:
    history_path = tmp_path / "performance_history.csv"
    summary = calculate_performance([1000.0, -400.0, 600.0])
    saved = append_performance_history(summary, history_path, recorded_at=datetime(2026, 7, 29, 15, 30, 0))
    assert saved is True
    rows = _read_history(history_path)
    assert len(rows) == 1
    assert rows[0]["recorded_at"] == "2026-07-29T15:30:00"
    assert rows[0]["total_trades"] == "3"
    assert rows[0]["winning_trades"] == "2"
    assert rows[0]["losing_trades"] == "1"
    assert rows[0]["net_profit"] == "1200.0"
    assert rows[0]["profit_factor"] == "4.0"
    assert rows[0]["maximum_drawdown"] == "400.0"


def test_append_performance_history_skips_duplicate(tmp_path: Path) -> None:
    history_path = tmp_path / "performance_history.csv"
    summary = calculate_performance([1000.0, -400.0])
    assert append_performance_history(summary, history_path, recorded_at=datetime(2026, 7, 29, 15, 30, 0)) is True
    assert append_performance_history(summary, history_path, recorded_at=datetime(2026, 7, 29, 16, 30, 0)) is False
    assert len(_read_history(history_path)) == 1


def test_append_performance_history_skips_empty_summary(tmp_path: Path) -> None:
    history_path = tmp_path / "performance_history.csv"
    assert append_performance_history(calculate_performance([]), history_path) is False
    assert not history_path.exists()


def test_append_performance_history_saves_changed_summary(tmp_path: Path) -> None:
    history_path = tmp_path / "performance_history.csv"
    append_performance_history(calculate_performance([1000.0, -400.0]), history_path)
    assert append_performance_history(calculate_performance([1000.0, -400.0, 800.0]), history_path) is True
    assert len(_read_history(history_path)) == 2


def test_append_performance_history_migrates_legacy_csv(tmp_path: Path) -> None:
    history_path = tmp_path / "performance_history.csv"
    legacy_fields = [
        "recorded_at", "total_trades", "winning_trades", "losing_trades", "break_even_trades",
        "win_rate", "gross_profit", "gross_loss", "net_profit", "average_profit", "average_loss",
        "largest_profit", "largest_loss", "profit_factor", "maximum_winning_streak", "maximum_losing_streak",
    ]
    with history_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=legacy_fields)
        writer.writeheader()
        writer.writerow({field: "0" for field in legacy_fields})
    assert append_performance_history(calculate_performance([100.0, -25.0]), history_path) is True
    with history_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        assert reader.fieldnames[-1] == "maximum_drawdown"
    assert rows[0]["maximum_drawdown"] == ""
    assert rows[1]["maximum_drawdown"] == "25.0"


def test_write_dashboard_saves_performance_history(tmp_path: Path) -> None:
    pnl_path = tmp_path / "paper_trade_pnls.json"
    pnl_path.write_text(json.dumps({"realized_trade_pnls": [1000.0, -400.0, 600.0]}, ensure_ascii=False), encoding="utf-8")
    write_dashboard_html(tmp_path)
    write_dashboard_html(tmp_path)
    history_path = tmp_path / "performance_history.csv"
    assert history_path.exists()
    rows = _read_history(history_path)
    assert len(rows) == 1
    assert rows[0]["total_trades"] == "3"
    assert rows[0]["net_profit"] == "1200.0"
    assert rows[0]["maximum_drawdown"] == "400.0"
