from config import ATR_LIST, RSI_LIST, MA_LIST, MIN_TRADES
from indicators import add_indicators
from strategy import create_buy_signal
from backtest import run_backtest


def find_best_setting(df):
    """最適な設定を探す"""

    best_result = None
    best_atr = None
    best_ma = None
    best_rsi = None
    all_results = []

    for atr in ATR_LIST:

        print(f"ATR倍率: {atr}")

        for ma_short, ma_middle, ma_long in MA_LIST:

            df_ma = add_indicators(
                df.copy(),
                ma_short,
                ma_middle,
                ma_long
            )

            for rsi_low, rsi_high in RSI_LIST:

                df_signal = create_buy_signal(
                    df_ma.copy(),
                    rsi_low,
                    rsi_high
                )

                result = run_backtest(df_signal, atr_multiplier=atr)
                eligible = result["trade_count"] >= MIN_TRADES

                all_results.append([
                    atr,
                    (ma_short, ma_middle, ma_long),
                    (rsi_low, rsi_high),
                    result["win_rate"],
                    result["total_profit"],
                    result["trade_count"],
                    result["total_profit"] / result["trade_count"] if result["trade_count"] > 0 else 0,
                    result["net_profit_yen"],
                    result["final_capital"],
                    result["total_commission"],
                    result["average_hold_days"],
                    result["max_drawdown"],
                    eligible,
                ])

                if not eligible:
                    continue

                if best_result is None or result["total_profit"] > best_result["total_profit"]:
                    best_result = result
                    best_atr = atr
                    best_ma = (ma_short, ma_middle, ma_long)
                    best_rsi = (rsi_low, rsi_high)

    return {
        "result": best_result,
        "atr": best_atr,
        "ma": best_ma,
        "rsi": best_rsi,
        "all_results": all_results,
    }
