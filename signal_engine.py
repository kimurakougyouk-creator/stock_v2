from __future__ import annotations

from typing import Any

import pandas as pd


def determine_signal(df: pd.DataFrame) -> dict[str, Any]:
    """最新日のデータに基づいて BUY / SELL / HOLD を判定する。"""
    if df.empty:
        return {
            "signal": "HOLD",
            "reason": "株価データが取得できませんでした。",
            "price": None,
            "ma_short": None,
            "ma_middle": None,
            "ma_long": None,
            "rsi": None,
            "macd": None,
            "signal_line": None,
            "atr": None,
        }

    latest = df.iloc[-1]
    price = float(latest["Close"])
    ma_short = float(latest["MA5"])
    ma_middle = float(latest["MA25"])
    ma_long = float(latest["MA75"])
    rsi = float(latest["RSI"])
    macd = float(latest["MACD"])
    signal_line = float(latest["Signal"])
    atr = float(latest["ATR"])

    reasons: list[str] = []

    if price > ma_short:
        reasons.append("最新価格が短期移動平均を上回っています。")
    else:
        reasons.append("最新価格が短期移動平均を下回っています。")

    if ma_short > ma_middle:
        reasons.append("短期移動平均が中期移動平均を上回っています。")
    else:
        reasons.append("短期移動平均が中期移動平均を下回っています。")

    if ma_middle > ma_long:
        reasons.append("中期移動平均が長期移動平均を上回っています。")
    else:
        reasons.append("中期移動平均が長期移動平均を下回っています。")

    if rsi >= 60:
        reasons.append("RSIが60以上で、買い圧力が強いと判断します。")
    elif rsi <= 40:
        reasons.append("RSIが40以下で、売り圧力が強いと判断します。")
    else:
        reasons.append("RSIは中立圏にあり、強い方向性は見えません。")

    if macd > signal_line:
        reasons.append("MACDがシグナルラインを上回っています。")
    else:
        reasons.append("MACDがシグナルラインを下回っています。")

    if atr > 0:
        reasons.append("ATRが0より大きく、ボラティリティが確認できます。")
    else:
        reasons.append("ATRが0のため、ボラティリティが低いと見なします。")

    signal = "HOLD"
    if price > ma_short and ma_short > ma_middle and ma_middle > ma_long and rsi >= 60 and macd > signal_line:
        signal = "BUY"
    elif price < ma_short and ma_short < ma_middle and ma_middle < ma_long and rsi <= 40 and macd < signal_line:
        signal = "SELL"

    return {
        "signal": signal,
        "reason": "｜".join(reasons),
        "price": price,
        "ma_short": ma_short,
        "ma_middle": ma_middle,
        "ma_long": ma_long,
        "rsi": rsi,
        "macd": macd,
        "signal_line": signal_line,
        "atr": atr,
    }
