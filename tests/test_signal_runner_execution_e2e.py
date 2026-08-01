from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import signal_runner


def test_signal_runner_uses_paper_sync_before_order(monkeypatch):
    events = []

    dummy_df = pd.DataFrame(
        {
            "Close": [2500.0],
            "High": [2550.0],
            "Low": [2450.0],
        }
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
    monkeypatch.setattr(
        signal_runner,
        "load_optimized_settings",
        lambda: {},
    )
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
        "calculate_consecutive_losses",
        lambda: 0,
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_available_cash",
        lambda initial_capital: float(initial_capital),
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
            max_portfolio_risk_rate=1.0,
            daily_loss_limit_yen=10_000.0,
            max_consecutive_losses=3,
            max_daily_buy_orders=999,
            max_daily_sell_orders=999,
            max_daily_trading_amount_yen=1_000_000_000.0,
            enable_paper_trading=True,
            live_trading_unlocked=False,
        ),
    )

    original_sync = signal_runner.build_paper_order_sync

    def tracked_sync(**kwargs):
        events.append(("sync", kwargs.copy()))
        return original_sync(**kwargs)

    def tracked_create(**kwargs):
        events.append(("create", kwargs.copy()))
        return {
            "side": kwargs["signal"],
            "shares": kwargs["shares"],
        }

    monkeypatch.setattr(
        signal_runner,
        "build_paper_order_sync",
        tracked_sync,
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        tracked_create,
    )
    monkeypatch.setattr(
        signal_runner.pd.DataFrame,
        "to_excel",
        lambda *args, **kwargs: None,
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert len(events) == 2

    sync_event, create_event = events

    assert sync_event[0] == "sync"
    assert create_event[0] == "create"

    assert sync_event[1] == {
        "ticker": "7203.T",
        "signal": "BUY",
        "shares": 100,
        "reference_price": 2500.0,
    }

    assert create_event[1] == {
        "ticker": "7203.T",
        "signal": "BUY",
        "shares": 100,
        "reference_price": 2500.0,
    }
