from pathlib import Path
from unittest.mock import Mock

import signal_runner


def test_generate_decision_report_safely_returns_report_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    report_file = tmp_path / "decision_log_report.csv"
    generator = Mock(
        return_value={
            "total_decisions": 3,
            "ordered_count": 1,
        }
    )

    monkeypatch.setattr(
        signal_runner,
        "generate_decision_log_report",
        generator,
    )
    monkeypatch.setattr(
        signal_runner,
        "DECISION_LOG_REPORT_FILE",
        report_file,
    )

    result = signal_runner._generate_decision_report_safely()

    assert result == str(report_file)
    generator.assert_called_once_with()


def test_generate_decision_report_safely_skips_missing_log(
    monkeypatch,
) -> None:
    generator = Mock(
        side_effect=FileNotFoundError("判断ログなし")
    )

    monkeypatch.setattr(
        signal_runner,
        "generate_decision_log_report",
        generator,
    )

    result = signal_runner._generate_decision_report_safely()

    assert result is None
    generator.assert_called_once_with()


def test_generate_decision_report_safely_handles_error(
    monkeypatch,
) -> None:
    generator = Mock(
        side_effect=RuntimeError("集計エラー")
    )

    monkeypatch.setattr(
        signal_runner,
        "generate_decision_log_report",
        generator,
    )

    result = signal_runner._generate_decision_report_safely()

    assert result is None
    generator.assert_called_once_with()
