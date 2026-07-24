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


def test_determine_signal_assigns_high_score_for_bullish_conditions():
    df = pd.DataFrame([
        {
            "Close": 120.0,
            "MA5": 115.0,
            "MA25": 110.0,
            "MA75": 105.0,
            "RSI": 80.0,
            "MACD": 2.5,
            "Signal": 0.5,
            "ATR": 3.0,
            "Volume": 2_000.0,
            "VOL20": 1_000.0,
        }
    ])

    result = determine_signal(df)

    assert result["signal"] == "BUY"
    assert result["score"] >= 80
    assert result["grade"] == "A"


def test_determine_signal_assigns_low_score_for_bearish_conditions():
    df = pd.DataFrame([
        {
            "Close": 80.0,
            "MA5": 85.0,
            "MA25": 90.0,
            "MA75": 95.0,
            "RSI": 20.0,
            "MACD": -2.5,
            "Signal": 0.5,
            "ATR": 0.0,
            "Volume": 500.0,
            "VOL20": 1_000.0,
        }
    ])

    result = determine_signal(df)

    assert result["signal"] == "SELL"
    assert result["score"] <= 20
    assert result["grade"] == "E"


def test_determine_signal_keeps_score_between_zero_and_hundred():
    df = pd.DataFrame([
        {
            "Close": 100.0,
            "MA5": 100.0,
            "MA25": 100.0,
            "MA75": 100.0,
            "RSI": 50.0,
            "MACD": 0.0,
            "Signal": 0.0,
            "ATR": 0.0,
            "Volume": 1_000.0,
            "VOL20": 1_000.0,
        }
    ])

    result = determine_signal(df)

    assert 0 <= result["score"] <= 100
    assert result["grade"] == "C"
