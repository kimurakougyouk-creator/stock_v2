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
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=True,
            enable_paper_trading=True,
            live_trading_unlocked=False,
        ),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []

def test_buy_quantity_is_limited_by_max_order_shares(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

    large_order_result = _technical_result("BUY")
    large_order_result["reference_shares"] = 500

    monkeypatch.setattr(
        signal_runner,
        "determine_signal",
        lambda *args, **kwargs: large_order_result,
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
    monkeypatch.setattr(
        signal_runner,
        "get_open_positions",
        lambda: {},
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
            emergency_stop=False,
            max_order_shares=100,
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

def test_daily_loss_limit_blocks_new_buy(monkeypatch):
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
        "calculate_daily_realized_pnl",
        lambda: -10_000.0,
    )
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
            max_order_shares=100,
            daily_loss_limit_yen=10_000.0,
            enable_paper_trading=True,
            live_trading_unlocked=False,
        ),
    )

    signal_runner.run_signal_scan(
        ["7203.T"],
        allow_orders=True,
        allow_email=False,
    )

    assert created_orders == []


def test_daily_loss_limit_does_not_block_sell(monkeypatch):
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
        lambda: {"7203.T": 100},
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_daily_realized_pnl",
        lambda: -10_000.0,
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
            emergency_stop=False,
            max_order_shares=100,
            daily_loss_limit_yen=10_000.0,
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
    assert created_orders[0]["signal"] == "SELL"

def test_consecutive_loss_limit_blocks_new_buy(monkeypatch):
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
        "calculate_daily_realized_pnl",
        lambda: 0.0,
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_consecutive_losses",
        lambda: 3,
    )
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
            max_order_shares=100,
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

    assert created_orders == []


def test_consecutive_loss_limit_does_not_block_sell(monkeypatch):
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
        lambda: {"7203.T": 100},
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_daily_realized_pnl",
        lambda: 0.0,
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_consecutive_losses",
        lambda: 3,
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
            emergency_stop=False,
            max_order_shares=100,
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
    assert created_orders[0]["signal"] == "SELL"

def test_available_cash_limits_buy_shares(monkeypatch):
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
        "calculate_available_cash",
        lambda initial_capital: 250_000.0,
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs) or {
            "side": kwargs["signal"],
            "shares": kwargs["shares"],
        },
    )
    monkeypatch.setattr(signal_runner, "LOT_SIZE", 100)
    monkeypatch.setattr(signal_runner, "TRADING_CAPITAL", 1_000_000)
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=False,
            max_order_shares=500,
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
    assert created_orders[0]["shares"] == 100


def test_available_cash_blocks_unaffordable_buy(monkeypatch):
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
        "calculate_available_cash",
        lambda initial_capital: 100_000.0,
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs),
    )
    monkeypatch.setattr(signal_runner, "LOT_SIZE", 100)
    monkeypatch.setattr(signal_runner, "TRADING_CAPITAL", 1_000_000)
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=False,
            max_order_shares=500,
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

    assert created_orders == []

def test_max_positions_blocks_new_buy(monkeypatch):
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
        lambda: {
            "6758.T": 100,
            "8306.T": 100,
            "9984.T": 100,
            "6861.T": 100,
            "8035.T": 100,
        },
    )
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
            max_order_shares=100,
            max_positions=5,
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

    assert created_orders == []


def test_buy_is_allowed_below_max_positions(monkeypatch):
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
        lambda: {
            "6758.T": 100,
            "8306.T": 100,
            "9984.T": 100,
            "6861.T": 100,
        },
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
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
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


def test_max_positions_does_not_block_sell(monkeypatch):
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
        lambda: {
            "7203.T": 100,
            "6758.T": 100,
            "8306.T": 100,
            "9984.T": 100,
            "6861.T": 100,
        },
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
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
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
    assert created_orders[0]["signal"] == "SELL"
    assert created_orders[0]["shares"] == 100

def test_buy_quantity_is_limited_by_position_allocation(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

    large_order_result = _technical_result("BUY")
    large_order_result["price"] = 1_000.0
    large_order_result["reference_shares"] = 500

    monkeypatch.setattr(
        signal_runner,
        "determine_signal",
        lambda *args, **kwargs: large_order_result,
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
        "calculate_available_cash",
        lambda initial_capital: float(initial_capital),
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs) or {
            "side": kwargs["signal"],
            "shares": kwargs["shares"],
        },
    )
    monkeypatch.setattr(signal_runner, "TRADING_CAPITAL", 1_000_000.0)
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=False,
            max_order_shares=500,
            max_positions=5,
            max_position_allocation=0.20,
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
    assert created_orders[0]["shares"] == 200


def test_buy_is_skipped_when_allocation_cannot_buy_one_lot(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

    expensive_result = _technical_result("BUY")
    expensive_result["price"] = 3_000.0
    expensive_result["reference_shares"] = 100

    monkeypatch.setattr(
        signal_runner,
        "determine_signal",
        lambda *args, **kwargs: expensive_result,
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
        "calculate_available_cash",
        lambda initial_capital: float(initial_capital),
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs),
    )
    monkeypatch.setattr(signal_runner, "TRADING_CAPITAL", 1_000_000.0)
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=0.20,
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

    assert created_orders == []


def test_position_allocation_does_not_block_sell(monkeypatch):
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
        lambda: {"7203.T": 100},
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
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=0.01,
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
    assert created_orders[0]["signal"] == "SELL"
    assert created_orders[0]["shares"] == 100

def test_buy_quantity_is_limited_by_portfolio_allocation(monkeypatch):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

    buy_result = _technical_result("BUY")
    buy_result["price"] = 1_000.0
    buy_result["reference_shares"] = 500

    monkeypatch.setattr(
        signal_runner,
        "determine_signal",
        lambda *args, **kwargs: buy_result,
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
        "calculate_available_cash",
        lambda initial_capital: 300_000.0,
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs) or {
            "side": kwargs["signal"],
            "shares": kwargs["shares"],
        },
    )
    monkeypatch.setattr(signal_runner, "TRADING_CAPITAL", 1_000_000.0)
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=False,
            max_order_shares=500,
            max_positions=5,
            max_position_allocation=1.0,
            max_portfolio_allocation=0.80,
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


def test_buy_is_skipped_when_portfolio_limit_cannot_buy_one_lot(
    monkeypatch,
):
    created_orders = []

    _prepare_common_mocks(monkeypatch, "BUY")

    buy_result = _technical_result("BUY")
    buy_result["price"] = 1_000.0
    buy_result["reference_shares"] = 100

    monkeypatch.setattr(
        signal_runner,
        "determine_signal",
        lambda *args, **kwargs: buy_result,
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
        "calculate_available_cash",
        lambda initial_capital: 250_000.0,
    )
    monkeypatch.setattr(
        signal_runner,
        "create_paper_order",
        lambda **kwargs: created_orders.append(kwargs),
    )
    monkeypatch.setattr(signal_runner, "TRADING_CAPITAL", 1_000_000.0)
    monkeypatch.setattr(
        signal_runner,
        "SETTINGS",
        SimpleNamespace(
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=1.0,
            max_portfolio_allocation=0.80,
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

    assert created_orders == []


def test_portfolio_allocation_does_not_block_sell(monkeypatch):
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
        lambda: {"7203.T": 100},
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
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=0.20,
            max_portfolio_allocation=0.0,
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
    assert created_orders[0]["signal"] == "SELL"
    assert created_orders[0]["shares"] == 100

def test_daily_buy_limit_blocks_new_buy(monkeypatch):
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
        "calculate_daily_buy_order_count",
        lambda: 3,
    )
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
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=1.0,
            max_portfolio_allocation=1.0,
            max_daily_buy_orders=3,
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

    assert created_orders == []


def test_buy_is_allowed_below_daily_buy_limit(monkeypatch):
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
        "calculate_daily_buy_order_count",
        lambda: 2,
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
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=1.0,
            max_portfolio_allocation=1.0,
            max_daily_buy_orders=3,
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


def test_daily_buy_limit_does_not_block_sell(monkeypatch):
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
        lambda: {"7203.T": 100},
    )
    monkeypatch.setattr(
        signal_runner,
        "calculate_daily_buy_order_count",
        lambda: 99,
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
            emergency_stop=False,
            max_order_shares=100,
            max_positions=5,
            max_position_allocation=0.20,
            max_portfolio_allocation=0.80,
            max_daily_buy_orders=3,
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
    assert created_orders[0]["signal"] == "SELL"
    assert created_orders[0]["shares"] == 100

