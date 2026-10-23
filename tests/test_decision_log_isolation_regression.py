"""Regression test for the decision_log.csv test-pollution incident.

Root cause: run_signal_scan() calls log_decision() unconditionally for every
ticker it evaluates. tests/test_signal_runner_time_stop.py and
tests/test_signal_runner_final_decision.py call run_signal_scan() without
mocking log_decision or redirecting decision_logger.LOG_FILE, so every run
of those test files appended real "7203.T" / ai_provider="test" rows
straight into the production results/decision_log.csv (confirmed: 1182 of
1227 rows dated 2026-09-27 through 2026-10-23 were this test artifact).

The fix is the autouse `isolate_signal_runner_decision_log` fixture in
conftest.py, which replaces signal_runner.log_decision itself with a no-op
for every test (not decision_logger.LOG_FILE -- a module-identity split
caused by test_decision_logger_package_migration.py's sys.modules-popping
test made a LOG_FILE-based redirect unreliable; see that fixture's
docstring). This test proves the no-op actually takes effect for a real
run_signal_scan() call, and that the production file is left alone.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import signal_runner

REAL_LOG_FILE = Path("results") / "decision_log.csv"


def test_signal_runner_log_decision_is_a_no_op_during_tests():
    # The autouse isolation fixture must have replaced signal_runner's own
    # log_decision attribute before this test body runs.
    calls = []
    signal_runner.log_decision(ticker="SHOULD_NOT_WRITE", final_signal="HOLD")
    assert calls == []
    assert not REAL_LOG_FILE.exists() or REAL_LOG_FILE.read_text(
        encoding="utf-8-sig"
    ).find("SHOULD_NOT_WRITE") == -1


def test_run_signal_scan_with_hold_technical_signal_does_not_touch_production_log(
    monkeypatch,
):
    real_log_existed_before = REAL_LOG_FILE.exists()
    real_log_bytes_before = (
        REAL_LOG_FILE.read_bytes() if real_log_existed_before else None
    )

    dummy_df = pd.DataFrame(
        {"Close": [2500.0], "High": [2550.0], "Low": [2450.0]}
    )

    monkeypatch.setattr(signal_runner, "_safe_download", lambda ticker: (dummy_df, None))
    monkeypatch.setattr(signal_runner, "load_optimized_settings", lambda: {})
    monkeypatch.setattr(
        signal_runner,
        "get_ticker_settings",
        lambda ticker, settings: {
            "ma_short": 5,
            "ma_middle": 20,
            "ma_long": 60,
            "rsi_low": 50,
            "rsi_high": 60,
            "atr_multiplier": 2.0,
        },
    )
    monkeypatch.setattr(signal_runner, "add_indicators", lambda df, **kwargs: df)
    monkeypatch.setattr(
        signal_runner,
        "determine_signal",
        lambda *args, **kwargs: {
            "signal": "HOLD",
            "reason": "test",
            "price": 2500.0,
            "ma_short": 2400.0,
            "ma_middle": 2300.0,
            "ma_long": 2200.0,
            "rsi": 60.0,
            "macd": 10.0,
            "signal_line": 5.0,
            "atr": 50.0,
            "score": 50,
            "grade": "C",
            "stop_price": 2400.0,
            "reference_shares": 0,
            "reference_amount_yen": 0,
            "max_loss_yen": 10000,
            "risk_per_share": 100.0,
            "position_sizing_reason": "test",
        },
    )
    monkeypatch.setattr(
        signal_runner,
        "judge_with_ai",
        lambda *args, **kwargs: SimpleNamespace(
            signal="HOLD",
            score=50,
            confidence=80.0,
            reason="AI hold",
            provider="test",
            available=True,
        ),
    )
    monkeypatch.setattr(signal_runner, "get_open_positions", lambda: {})
    monkeypatch.setattr(signal_runner, "calculate_position_holding_days", lambda ticker: None)
    monkeypatch.setattr(signal_runner, "calculate_daily_realized_pnl", lambda: 0.0)
    monkeypatch.setattr(signal_runner, "calculate_consecutive_losses", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_sell_order_count", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_trading_amount", lambda: 0.0)
    monkeypatch.setattr(signal_runner.pd.DataFrame, "to_excel", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=1.0,
            max_portfolio_allocation=1.0,
            max_daily_buy_orders=3,
            max_daily_sell_orders=3,
            max_daily_trading_amount_yen=1_000_000.0,
            repurchase_cooldown_minutes=60,
            daily_loss_limit_yen=10_000.0,
            max_consecutive_losses=3,
            max_holding_days=30,
            enable_paper_trading=True,
            live_trading_unlocked=False,
        ),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    if real_log_existed_before:
        assert REAL_LOG_FILE.read_bytes() == real_log_bytes_before
    else:
        assert not REAL_LOG_FILE.exists()
