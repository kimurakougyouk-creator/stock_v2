import pandas as pd

from signal_engine import determine_signal


def test_determine_signal_returns_buy_when_trend_is_bullish():
    df = pd.DataFrame([
        {
            "Close": 110.0,
            "MA5": 105.0,
            "MA25": 100.0,
            "MA75": 95.0,
            "RSI": 65.0,
            "MACD": 1.5,
            "Signal": 0.5,
            "ATR": 2.0,
        }
    ])

    result = determine_signal(df)

    assert result["signal"] == "BUY"
    assert "買い" in result["reason"] or "BUY" in result["reason"]


def test_determine_signal_returns_sell_when_trend_is_bearish():
    df = pd.DataFrame([
        {
            "Close": 90.0,
            "MA5": 95.0,
            "MA25": 100.0,
            "MA75": 105.0,
            "RSI": 35.0,
            "MACD": -1.5,
            "Signal": -0.5,
            "ATR": 2.0,
        }
    ])

    result = determine_signal(df)

    assert result["signal"] == "SELL"
    assert "売り" in result["reason"] or "SELL" in result["reason"]
