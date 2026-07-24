import pandas as pd

from backtest import run_backtest


def _df(prices):
    return pd.DataFrame(
        {
            "Close": prices,
            "ATR": [100.0] * len(prices),
            "Buy": [True] + [False] * (len(prices) - 1),
        },
        index=pd.date_range("2026-01-01", periods=len(prices), freq="D"),
    )


def test_stop_loss_closes_position_at_default_three_percent_drop():
    result = run_backtest(_df([100.0, 96.9]))

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "stop_loss"
    assert result["trades"][0]["profit"] < -3.0


def test_take_profit_closes_position_at_default_six_percent_gain():
    result = run_backtest(_df([100.0, 106.1]))

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "take_profit"
    assert result["trades"][0]["profit"] > 6.0


def test_risk_rates_can_be_overridden():
    result = run_backtest(_df([100.0, 104.1]), take_profit_rate=0.04)

    assert result["trade_count"] == 1
    assert result["trades"][0]["exit_reason"] == "take_profit"
