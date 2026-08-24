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


@pytest.fixture(autouse=True)
def isolate_signal_runner_daily_state(monkeypatch, request):
    """Keep signal-runner unit tests independent of durable daily order state."""

    if request.node.fspath.basename != "test_signal_runner_final_decision.py":
        return

    import signal_runner

    monkeypatch.setattr(signal_runner, "calculate_daily_buy_order_count", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_sell_order_count", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_realized_pnl", lambda: 0.0)
    monkeypatch.setattr(signal_runner, "calculate_daily_trading_amount", lambda: 0.0)
    monkeypatch.setattr(
        signal_runner,
        "calculate_repurchase_cooldown_remaining_minutes",
        lambda *args, **kwargs: 0,
    )
