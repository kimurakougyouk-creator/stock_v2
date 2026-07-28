from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import signal_runner


def _technical_result(signal: str = "HOLD") -> dict:
    return {
        "signal": signal,
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
    }


def _prepare_common_mocks(
    monkeypatch,
    *,
    held_shares: int,
    holding_days: int | None,
    emergency_stop: bool = False,
    max_holding_days: int = 30,
) -> list[dict]:
    dummy_df = pd.DataFrame(
        {
            "Close": [2500.0],
            "High": [2550.0],
            "Low": [2450.0],
        }
    )
    created_orders: list[dict] = []

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
        lambda *args, **kwargs: _technical_result("HOLD"),
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
    monkeypatch.setattr(
        signal_runner,
        "get_open_positions",
        lambda: (
            {"7203.T": held_shares}
            if held_shares > 0
            else {}
        ),
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_position_holding_days",
        lambda ticker: holding_days,
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_daily_realized_pnl",
        lambda: 0.0,
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_consecutive_losses",
        lambda: 0,
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_daily_sell_order_count",
        lambda: 0,
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_daily_trading_amount",
        lambda: 0.0,
    )
    monkeypatch.setattr(
        signal_runner.pd.DataFrame,
        "to_excel",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs) or {
            "side": kwargs["signal"],
            "shares": kwargs["shares"],
        },
    )
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=emergency_stop,
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
            max_holding_days=max_holding_days,
            enable_paper_trading=True,
            live_trading_unlocked=False,
        ),
    )

    return created_orders


def test_time_stop_changes_hold_to_sell(monkeypatch):
    created_orders = _prepare_common_mocks(
        monkeypatch,
        held_shares=40,
        holding_days=30,
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert len(created_orders) == 1
    assert created_orders[0]["signal"] == "SELL"
    assert created_orders[0]["shares"] == 40


def test_time_stop_sells_all_shares_over_normal_order_limit(
    monkeypatch,
):
    created_orders = _prepare_common_mocks(
        monkeypatch,
        held_shares=300,
        holding_days=45,
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert len(created_orders) == 1
    assert created_orders[0]["signal"] == "SELL"
    assert created_orders[0]["shares"] == 300


def test_time_stop_does_not_trigger_before_limit(
    monkeypatch,
):
    created_orders = _prepare_common_mocks(
        monkeypatch,
        held_shares=100,
        holding_days=29,
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []


def test_time_stop_does_not_trigger_without_position(
    monkeypatch,
):
    created_orders = _prepare_common_mocks(
        monkeypatch,
        held_shares=0,
        holding_days=None,
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []


def test_time_stop_can_be_disabled_with_zero_days(
    monkeypatch,
):
    created_orders = _prepare_common_mocks(
        monkeypatch,
        held_shares=100,
        holding_days=100,
        max_holding_days=0,
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []


def test_emergency_stop_blocks_time_stop_order(
    monkeypatch,
):
    created_orders = _prepare_common_mocks(
        monkeypatch,
        held_shares=100,
        holding_days=40,
        emergency_stop=True,
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []
