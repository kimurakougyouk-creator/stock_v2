from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import signal_runner


def _technical_result(signal: str = "BUY") -> dict:
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
        "score": 90,
        "grade": "A",
        "stop_price": 2400.0,
        "reference_shares": 100,
        "reference_amount_yen": 250000,
        "max_loss_yen": 10000,
        "risk_per_share": 100.0,
        "position_sizing_reason": "test",
    }


def _prepare_common_mocks(monkeypatch, technical_signal: str) -> None:
    dummy_df = pd.DataFrame(
        {
            "Close": [2500.0],
            "High": [2550.0],
            "Low": [2450.0],
        }
    )

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
        lambda *args, **kwargs: _technical_result(technical_signal),
    )
    monkeypatch.setattr(
        signal_runner.pd.DataFrame,
        "to_excel",
        lambda *args, **kwargs: None,
    )
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
    monkeypatch.setattr(signal_runner, "calculate_daily_buy_order_count", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_sell_order_count", lambda: 0)
    monkeypatch.setattr(signal_runner, "calculate_daily_realized_pnl", lambda: 0.0)
    monkeypatch.setattr(signal_runner, "calculate_daily_trading_amount", lambda: 0.0)
    monkeypatch.setattr(
        signal_runner,
        "calculate_repurchase_cooldown_remaining_minutes",
        lambda *args, **kwargs: 0,
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_position_holding_days",
        lambda ticker: 0,
    )
    monkeypatch.setattr(
        signal_runner,
        "update_trailing_high_price",
        lambda ticker, price, held_shares=0: price if held_shares > 0 else None,
    )


def test_final_hold_does_not_create_order(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

    monkeypatch.setattr(
        signal_runner,
        "judge_with_ai",
        lambda *args, **kwargs: SimpleNamespace(
            signal="SELL",
            score=20,
            confidence=95.0,
            reason="AI disagrees",
            provider="test",
            available=True,
        ),
    )
    monkeypatch.setattr(signal_runner, "get_open_positions", lambda: {})
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []


def test_final_buy_creates_order(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

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
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=1.0,
            daily_loss_limit_yen=10_000.0,
            max_consecutive_losses=3,
            enable_paper_trading=True,
            live_trading_unlocked=False,
        ),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert len(created_orders) == 1
    assert created_orders[0]["signal"] == "BUY"
    assert created_orders[0]["shares"] == 100


def test_paper_trading_disabled_does_not_create_order(monkeypatch):
    from types import SimpleNamespace

    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

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
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs),
    )
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=False,
            enable_paper_trading=False,
            live_trading_unlocked=False,
        ),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []


def test_buy_is_blocked_when_position_already_exists(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

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
    monkeypatch.setattr(
        signal_runner,
        "get_open_positions",
        lambda: {"7203.T": 100},
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []


def test_sell_is_blocked_when_position_does_not_exist(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "SELL")

    monkeypatch.setattr(
        signal_runner,
        "judge_with_ai",
        lambda *args, **kwargs: SimpleNamespace(
            signal="SELL",
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
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []


def test_sell_quantity_is_limited_to_held_shares(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "SELL")

    monkeypatch.setattr(
        signal_runner,
        "judge_with_ai",
        lambda *args, **kwargs: SimpleNamespace(
            signal="SELL",
            score=90,
            confidence=95.0,
            reason="AI agrees",
            provider="test",
            available=True,
        ),
    )
    monkeypatch.setattr(
        signal_runner,
        "get_open_positions",
        lambda: {"7203.T": 40},
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs) or {
            "side": kwargs["signal"],
            "shares": kwargs["shares"],
        },
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert len(created_orders) == 1
    assert created_orders[0]["signal"] == "SELL"
    assert created_orders[0]["shares"] == 40

def test_emergency_stop_blocks_paper_order(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

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
    monkeypatch.setattr(
        signal_runner,
        "get_open_positions",
        lambda: {},
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs),
    )

    original_settings = signal_runner.SETTINGS
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            **{
                key: getattr(original_settings, key)
                for key in dir(original_settings)
                if not key.startswith("_")
                and not callable(getattr(original_settings, key))
            },
            emergency_stop=True,
        ),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []
