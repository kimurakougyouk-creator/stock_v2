from __future__ import annotations

import csv

import pytest

from decision_log_report import generate_decision_log_report


def write_decision_log(
    log_file,
    rows,
) -> None:
    log_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with log_file.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "Timestamp",
                "Ticker",
                "FinalSignal",
                "Ordered",
                "Reason",
                "AISignal",
                "AIConfidence",
                "TechnicalSignal",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_generate_decision_log_report_creates_summary(
    tmp_path,
) -> None:
    log_file = tmp_path / "results" / "decision_log.csv"
    report_file = (
        tmp_path
        / "results"
        / "decision_log_report.csv"
    )

    write_decision_log(
        log_file,
        [
            {
                "Timestamp": "2026-07-29 07:00:00",
                "Ticker": "7203.T",
                "FinalSignal": "BUY",
                "Ordered": "YES",
                "Reason": "AI最終判定",
                "AISignal": "BUY",
                "AIConfidence": "80.0",
                "TechnicalSignal": "BUY",
            },
            {
                "Timestamp": "2026-07-29 07:01:00",
                "Ticker": "6758.T",
                "FinalSignal": "SELL",
                "Ordered": "NO",
                "Reason": "リスク管理",
                "AISignal": "SELL",
                "AIConfidence": "70.0",
                "TechnicalSignal": "SELL",
            },
            {
                "Timestamp": "2026-07-29 07:02:00",
                "Ticker": "7203.T",
                "FinalSignal": "BUY",
                "Ordered": "YES",
                "Reason": "AI最終判定",
                "AISignal": "BUY",
                "AIConfidence": "90.0",
                "TechnicalSignal": "BUY",
            },
        ],
    )

    result = generate_decision_log_report(
        log_file=log_file,
        report_file=report_file,
    )

    assert result["total_decisions"] == 3
    assert result["ordered_count"] == 2
    assert result["not_ordered_count"] == 1
    assert result["order_rate"] == 66.7
    assert result["average_ai_confidence"] == 80.0
    assert result["final_signal_counts"] == {
        "BUY": 2,
        "SELL": 1,
    }
    assert result["ticker_counts"] == {
        "7203.T": 2,
        "6758.T": 1,
    }
    assert result["reason_counts"] == {
        "AI最終判定": 2,
        "リスク管理": 1,
    }
    assert result["not_ordered_reason_counts"] == {
        "リスク管理": 1,
    }
    assert report_file.exists()

    report_rows = list(
        csv.DictReader(
            report_file.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            )
        )
    )

    assert {
        "Category": "Reason",
        "Item": "AI最終判定",
        "Value": "2",
    } in report_rows
    assert {
        "Category": "NotOrderedReason",
        "Item": "リスク管理",
        "Value": "1",
    } in report_rows


def test_generate_decision_log_report_handles_empty_log(
    tmp_path,
) -> None:
    log_file = tmp_path / "results" / "decision_log.csv"
    report_file = (
        tmp_path
        / "results"
        / "decision_log_report.csv"
    )

    write_decision_log(
        log_file,
        [],
    )

    result = generate_decision_log_report(
        log_file=log_file,
        report_file=report_file,
    )

    assert result["total_decisions"] == 0
    assert result["ordered_count"] == 0
    assert result["not_ordered_count"] == 0
    assert result["order_rate"] == 0.0
    assert result["average_ai_confidence"] == 0.0
    assert result["reason_counts"] == {}
    assert result["not_ordered_reason_counts"] == {}
    assert report_file.exists()


def test_generate_decision_log_report_rejects_missing_log(
    tmp_path,
) -> None:
    log_file = tmp_path / "missing.csv"
    report_file = tmp_path / "report.csv"

    with pytest.raises(
        FileNotFoundError,
        match="判断ログが見つかりません",
    ):
        generate_decision_log_report(
            log_file=log_file,
            report_file=report_file,
        )
