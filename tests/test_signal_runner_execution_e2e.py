from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import signal_runner


BAR_TIME = pd.Timestamp("2026-08-26 09:00:00+09:00")


def _install_actionable_buy_case(monkeypatch, *, enable_ibkr_paper: bool = True):
    logged: list[dict] = []

    dummy_df = pd.DataFrame(
        {
            "Close": [2500.0],
            "High": [2550.0],
            "Low": [2450.0],
        },
        index=[BAR_TIME],
    )

    technical_result = {
        "signal": "BUY",
        "reason": "e2e test",
        "price": 2500.0,
        "ma_short": 2400.0,
        "ma_middle": 2300.0,
        "ma_long": 2200.0,
        "rsi": 60.0,
        "macd": 10.0,
        "signal_line": 5.0,
        "atr": 50.0,
        "score": 90,
        "grade": "A",
        "stop_price": 2400.0,
        "reference_shares": 100,
        "reference_amount_yen": 250000.0,
        "max_loss_yen": 10000.0,
        "risk_per_share": 100.0,
        "position_sizing_reason": "e2e test",
    }

    monkeypatch.setattr(
        signal_runner,
        "_safe_download",
        lambda ticker: (dummy_df, None),
    )
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
    monkeypatch.setattr(
        signal_runner,
        "add_indicators",
        lambda df, **kwargs: df,
    )
    monkeypatch.setattr(
        signal_runner,
        "determine_signal",
        lambda *args, **kwargs: technical_result,
    )
    monkeypatch.setattr(
        signal_runner,
        "judge_with_ai",
        lambda *args, **kwargs: SimpleNamespace(
            signal="BUY",
            score=90,
            confidence=95.0,
            reason="AI agrees",
            provider="test",
            available=True,
        ),
    )

    monkeypatch.setattr(signal_runner, "get_open_positions", lambda: {})
    monkeypatch.setattr(
        signal_runner,
        "update_trailing_high_price",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(signal_runner, "calculate_daily_realized_pnl", lambda: 0.0)
    monkeypatch.setattr(signal_runner, "calculate_consecutive_losses", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_buy_order_count", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_sell_order_count", lambda: 0)
    monkeypatch.setattr(
        signal_runner,
        "calculate_repurchase_cooldown_remaining_minutes",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_available_cash",
        lambda initial_capital: float(initial_capital),
    )
    monkeypatch.setattr(signal_runner, "calculate_open_position_risk", lambda *args, **kwargs: 0.0)
    monkeypatch.setattr(signal_runner, "load_paper_orders", lambda: [])
    monkeypatch.setattr(signal_runner, "calculate_position_size", lambda **kwargs: 100)
    monkeypatch.setattr(signal_runner, "calculate_daily_trading_amount", lambda: 0.0)
    monkeypatch.setattr(
        signal_runner,
        "log_decision",
        lambda **kwargs: logged.append(kwargs.copy()),
    )
    monkeypatch.setattr(
        signal_runner,
        "_generate_decision_report_safely",
        lambda: None,
    )
    monkeypatch.setattr(
        signal_runner.pd.DataFrame,
        "to_excel",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            minimum_ai_confidence=70.0,
            emergency_stop=False,
            trailing_stop_percent=5.0,
            max_holding_days=30,
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=1.0,
            max_portfolio_allocation=1.0,
            max_portfolio_risk_rate=1.0,
            daily_loss_limit_yen=10_000.0,
            max_consecutive_losses=3,
            max_daily_buy_orders=999,
            max_daily_sell_orders=999,
            repurchase_cooldown_minutes=0,
            max_daily_trading_amount_yen=1_000_000_000.0,
            enable_paper_trading=True,
            enable_ibkr_paper=enable_ibkr_paper,
            live_trading_unlocked=False,
        ),
    )

    return logged


def test_signal_runner_dispatches_verified_order_only_once_via_ibkr(monkeypatch):
    logged = _install_actionable_buy_case(monkeypatch)
    calls: list[dict] = []

    monkeypatch.setattr(
        signal_runner,
        "verified_paper_test_quantity_for_ticker",
        lambda ticker: 100 if ticker == "9432.T" else None,
    )

    def fake_execute(**kwargs):
        calls.append(kwargs.copy())
        return SimpleNamespace(
            attempted=True,
            reason="submitted to IBKR Paper execution service",
            broker_result=SimpleNamespace(
                sent=True,
                status="FILLED",
                message="filled",
            ),
        )

    monkeypatch.setattr(
        signal_runner,
        "execute_approved_signal_via_ibkr_paper",
        fake_execute,
    )

    signal_runner.run_signal_scan(
        ["9432.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert calls == [
        {
            "ticker": "9432.T",
            "signal": "BUY",
            "shares": 100,
            "order_intent_id": (
                "signal-runner:9432.T:BUY:100:"
                "2026-08-26 09:00:00+09:00"
            ),
        }
    ]
    assert len(logged) == 1
    assert logged[0]["ticker"] == "9432.T"
    assert logged[0]["final_signal"] == "BUY"
    assert logged[0]["ordered"] is True


def test_signal_runner_blocks_unverified_ticker_before_ibkr_dispatch(monkeypatch):
    logged = _install_actionable_buy_case(monkeypatch)
    calls: list[dict] = []

    monkeypatch.setattr(
        signal_runner,
        "verified_paper_test_quantity_for_ticker",
        lambda ticker: None,
    )
    monkeypatch.setattr(
        signal_runner,
        "execute_approved_signal_via_ibkr_paper",
        lambda **kwargs: calls.append(kwargs.copy()),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert calls == []
    assert len(logged) == 1
    assert logged[0]["ordered"] is False


def test_signal_runner_requires_explicit_ibkr_paper_opt_in(monkeypatch):
    logged = _install_actionable_buy_case(
        monkeypatch,
        enable_ibkr_paper=False,
    )
    calls: list[dict] = []

    monkeypatch.setattr(
        signal_runner,
        "verified_paper_test_quantity_for_ticker",
        lambda ticker: 100,
    )
    monkeypatch.setattr(
        signal_runner,
        "execute_approved_signal_via_ibkr_paper",
        lambda **kwargs: calls.append(kwargs.copy()),
    )

    signal_runner.run_signal_scan(
        ["9432.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert calls == []
    assert len(logged) == 1
    assert logged[0]["ordered"] is False


def test_signal_order_intent_id_is_deterministic_for_same_bar():
    first = signal_runner._build_signal_order_intent_id(
        ticker="9432.T",
        signal="BUY",
        shares=100,
        bar_key=BAR_TIME,
    )
    second = signal_runner._build_signal_order_intent_id(
        ticker="9432.t",
        signal="buy",
        shares=100,
        bar_key=BAR_TIME,
    )

    assert first == second
    assert first == (
        "signal-runner:9432.T:BUY:100:"
        "2026-08-26 09:00:00+09:00"
    )
