from __future__ import annotations

import math
from typing import Any

import pandas as pd

from config import LOT_SIZE, RISK_PER_TRADE_RATE, TRADING_CAPITAL


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return numeric


def _grade_from_score(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "E"


def _calculate_position_sizing(
    price: float | None,
    atr: float | None,
    atr_multiplier: float = 2.0,
) -> tuple[int, float, float, float, str]:
    if price is None or price <= 0:
        return 0, 0.0, 0.0, 0.0, "価格が0以下のため、参考株数は0です。"

    if atr is None or atr <= 0:
        return 0, 0.0, 0.0, 0.0, "ATRが0または未計測のため、参考株数は0です。"

    stop_price = max(price * 0.97, price - (atr * atr_multiplier))
    risk_per_share = price - stop_price

    if risk_per_share <= 0:
        return 0, stop_price, risk_per_share, 0.0, "損切り価格が現在価格以上のため、参考株数は0です。"

    max_loss_yen = TRADING_CAPITAL * RISK_PER_TRADE_RATE
    risk_based_shares = max_loss_yen / risk_per_share
    capital_based_shares = TRADING_CAPITAL / price
    reference_shares_float = min(risk_based_shares, capital_based_shares)
    reference_shares = int(math.floor(reference_shares_float / LOT_SIZE) * LOT_SIZE)

    if reference_shares < LOT_SIZE:
        return 0, stop_price, risk_per_share, max_loss_yen, f"参考株数が{LOT_SIZE}株未満のため0株としました。"

    return reference_shares, stop_price, risk_per_share, max_loss_yen, f"損失許容と資金基準の小さい方を採用し、{reference_shares}株としました。"


def determine_signal(
    df: pd.DataFrame,
    rsi_low: float = 60,
    rsi_high: float = 70,
    atr_multiplier: float = 2.0,
) -> dict[str, Any]:
    """銘柄別設定を使ってBUY・SELL・HOLDを判定する。"""
    rsi_sell = 100 - rsi_low
    rsi_strong_sell = 100 - rsi_high
    default_result = {
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
        "score": 0,
        "grade": "E",
        "stop_price": None,
        "risk_per_share": None,
        "max_loss_yen": None,
        "reference_shares": 0,
        "reference_amount_yen": None,
        "position_sizing_reason": "データ不足のため、参考株数は0です。",
    }

    if df.empty:
        return default_result

    latest = df.iloc[-1]
    price = _safe_float(latest.get("Close"))
    ma_short = _safe_float(latest.get("MA5"))
    ma_middle = _safe_float(latest.get("MA25"))
    ma_long = _safe_float(latest.get("MA75"))
    rsi = _safe_float(latest.get("RSI"))
    macd = _safe_float(latest.get("MACD"))
    signal_line = _safe_float(latest.get("Signal"))
    atr = _safe_float(latest.get("ATR"))
    volume = _safe_float(latest.get("Volume"))
    vol20 = _safe_float(latest.get("VOL20"))

    reasons: list[str] = []

    if price is None or ma_short is None or ma_middle is None or ma_long is None:
        reasons.append("一部の移動平均指標が取得できないため、保守的にHOLDとします。")
    else:
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

    if rsi is None:
        reasons.append("RSIが取得できないため、評価を保留します。")
    elif rsi >= rsi_high:
        reasons.append(f"RSIが{rsi_high:g}以上で、買い圧力が強いと判断します。")
    elif rsi >= rsi_low:
        reasons.append(f"RSIが{rsi_low:g}以上で、買い圧力がやや強いです。")
    elif rsi <= rsi_strong_sell:
        reasons.append(f"RSIが{rsi_strong_sell:g}以下で、売り圧力が強いと判断します。")
    elif rsi <= rsi_sell:
        reasons.append(f"RSIが{rsi_sell:g}以下で、売り圧力がやや強いです。")
    else:
        reasons.append("RSIは中立圏にあり、強い方向性は見えません。")

    if macd is None or signal_line is None:
        reasons.append("MACDとシグナルラインが取得できないため、判断を保留します。")
    elif macd > signal_line:
        reasons.append("MACDがシグナルラインを上回っています。")
    else:
        reasons.append("MACDがシグナルラインを下回っています。")

    if atr is None:
        reasons.append("ATRが取得できないため、ボラティリティは不明です。")
    elif atr > 0:
        reasons.append("ATRが0より大きく、ボラティリティが確認できます。")
    else:
        reasons.append("ATRが0のため、ボラティリティが低いと見なします。")

    if volume is None or vol20 is None:
        reasons.append("出来高の比較ができないため、ボリューム判断は保留します。")
    elif volume > vol20:
        reasons.append("出来高が20日平均出来高を上回っています。")
    elif volume < vol20 * 0.5:
        reasons.append("出来高が20日平均出来高の半分を下回っています。")
    else:
        reasons.append("出来高は20日平均近辺です。")

    score = 50.0

    if price is not None and ma_short is not None:
        if price > ma_short:
            score += 12
        elif price < ma_short:
            score -= 12

    if ma_short is not None and ma_middle is not None:
        if ma_short > ma_middle:
            score += 8
        elif ma_short < ma_middle:
            score -= 8

    if ma_middle is not None and ma_long is not None:
        if ma_middle > ma_long:
            score += 8
        elif ma_middle < ma_long:
            score -= 8

    if price is not None and ma_middle is not None:
        if price > ma_middle:
            score += 6
        elif price < ma_middle:
            score -= 6

    if price is not None and ma_long is not None:
        if price > ma_long:
            score += 6
        elif price < ma_long:
            score -= 6

    if rsi is not None:
        if rsi >= rsi_high:
            score += 16
        elif rsi >= rsi_low:
            score += 10
        elif rsi >= 50:
            score += 4
        elif rsi <= rsi_strong_sell:
            score -= 16
        elif rsi <= rsi_sell:
            score -= 10

    if macd is not None and signal_line is not None:
        if macd > signal_line:
            score += 12
        elif macd < signal_line:
            score -= 12
        if macd > 0:
            score += 3
        elif macd < 0:
            score -= 3

    if atr is not None and atr > 0:
        score += 3

    if volume is not None and vol20 is not None:
        if volume > vol20:
            score += 6
        elif volume < vol20 * 0.5:
            score -= 6

    score = max(0.0, min(100.0, float(score)))

    signal = "HOLD"
    if price is not None and ma_short is not None and ma_middle is not None and ma_long is not None and rsi is not None and macd is not None and signal_line is not None:
        if price > ma_short and ma_short > ma_middle and ma_middle > ma_long and rsi >= rsi_low and macd > signal_line:
            signal = "BUY"
        elif price < ma_short and ma_short < ma_middle and ma_middle < ma_long and rsi <= rsi_sell and macd < signal_line:
            signal = "SELL"

    reference_shares = 0
    stop_price = None
    risk_per_share = None
    max_loss_yen = None
    reference_amount_yen = None
    position_sizing_reason = "BUY判定ではないため、参考株数は0です。"

    if signal == "BUY":
        reference_shares, stop_price, risk_per_share, max_loss_yen, position_sizing_reason = _calculate_position_sizing(price, atr, atr_multiplier)
        reference_amount_yen = reference_shares * price if price is not None else None
    else:
        position_sizing_reason = "BUY判定ではないため、参考株数は0です。"

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
        "score": score,
        "grade": _grade_from_score(score),
        "stop_price": stop_price,
        "risk_per_share": risk_per_share,
        "max_loss_yen": max_loss_yen,
        "reference_shares": reference_shares,
        "reference_amount_yen": reference_amount_yen,
        "position_sizing_reason": position_sizing_reason,
    }
