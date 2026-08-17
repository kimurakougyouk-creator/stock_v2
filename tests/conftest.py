import pytest

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# TEST_DECISION_REPORT_ISOLATION
@pytest.fixture(autouse=True)
def isolate_signal_runner_decision_report(monkeypatch, tmp_path):
    """テスト中の判断レポートを一時フォルダへ隔離する。"""

    try:
        import signal_runner
        from decision_log_report import generate_decision_log_report
    except ImportError:
        return

    temporary_report = tmp_path / "decision_log_report.csv"

    def generate_temporary_report():
        return generate_decision_log_report(
            report_file=temporary_report,
        )

    monkeypatch.setattr(
        signal_runner,
        "generate_decision_log_report",
        generate_temporary_report,
    )
