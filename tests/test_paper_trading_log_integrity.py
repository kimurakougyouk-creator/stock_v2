from pathlib import Path

from ai_asset_platform.reports.paper_trading_log_integrity import (
    count_decision_log_rows,
    evaluate_log_integrity,
)


def test_count_decision_log_rows(tmp_path):
    log_file = tmp_path / "decision_log.csv"

    log_file.write_text(
        "Timestamp,Ticker\n"
        "2026-08-02 10:00:00,7203.T\n"
        "2026-08-02 10:00:01,6758.T\n",
        encoding="utf-8",
    )

    assert count_decision_log_rows(log_file) == 2


def test_count_missing_log_returns_zero(tmp_path):
    log_file = tmp_path / "missing.csv"

    assert count_decision_log_rows(log_file) == 0


def test_log_integrity_normal():
    result = evaluate_log_integrity(
        before_count=100,
        after_count=110,
        expected_added=10,
    )

    assert result.is_valid is True
    assert result.actual_added == 10
    assert result.before_count == 100
    assert result.after_count == 110


def test_log_integrity_detects_missing_rows():
    result = evaluate_log_integrity(
        before_count=100,
        after_count=105,
        expected_added=10,
    )

    assert result.is_valid is False
    assert result.actual_added == 5
    assert "想定と一致しません" in result.message


def test_log_integrity_detects_no_growth():
    result = evaluate_log_integrity(
        before_count=100,
        after_count=100,
        expected_added=10,
    )

    assert result.is_valid is False
    assert result.actual_added == 0
