from __future__ import annotations

import csv

import decision_logger


def test_log_decision_creates_csv_with_correct_values(
    tmp_path,
    monkeypatch,
) -> None:
    log_file = tmp_path / "results" / "decision_log.csv"
    monkeypatch.setattr(decision_logger, "LOG_FILE", log_file)

    decision_logger.log_decision(
        ticker="7203.T",
        final_signal="BUY",
        ordered=True,
        reason="AI最終判定",
        ai_signal="BUY",
        ai_confidence=82.34,
        technical_signal="BUY",
    )

    assert log_file.exists()

    with log_file.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 1
    assert rows[0]["Ticker"] == "7203.T"
    assert rows[0]["FinalSignal"] == "BUY"
    assert rows[0]["Ordered"] == "YES"
    assert rows[0]["Reason"] == "AI最終判定"
    assert rows[0]["AISignal"] == "BUY"
    assert rows[0]["AIConfidence"] == "82.3"
    assert rows[0]["TechnicalSignal"] == "BUY"
    assert rows[0]["Timestamp"]


def test_log_decision_appends_without_duplicate_header(
    tmp_path,
    monkeypatch,
) -> None:
    log_file = tmp_path / "results" / "decision_log.csv"
    monkeypatch.setattr(decision_logger, "LOG_FILE", log_file)

    decision_logger.log_decision(
        ticker="7203.T",
        final_signal="BUY",
        ordered=True,
        reason="AI最終判定",
        ai_signal="BUY",
        ai_confidence=80.0,
        technical_signal="BUY",
    )
    decision_logger.log_decision(
        ticker="6758.T",
        final_signal="SELL",
        ordered=False,
        reason="リスク管理",
        ai_signal="SELL",
        ai_confidence=75.0,
        technical_signal="SELL",
    )

    with log_file.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        raw_rows = list(csv.reader(file))

    assert len(raw_rows) == 3
    assert raw_rows[0].count("Timestamp") == 1
    assert raw_rows[1][1] == "7203.T"
    assert raw_rows[2][1] == "6758.T"
    assert raw_rows[2][3] == "NO"
