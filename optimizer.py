from config import ATR_LIST, RSI_LIST, MA_LIST
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

        result = run_backtest(
            create_buy_signal(
                add_indicators(df.copy())
            ),
            atr_multiplier=atr
        )

        if best_result is None:
            best_result = result
            best_atr = atr

        elif result["total_profit"] > best_result["total_profit"]:
            best_result = result
            best_atr = atr

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

                profit_yen = result["total_profit"] / 100 * 1_000_000
                drawdown = result["max_drawdown"]

                all_results.append([
                    atr,
                    (ma_short, ma_middle, ma_long),
                    (rsi_low, rsi_high),
                    result["win_rate"],
                    result["total_profit"],
                    result["trade_count"],
                    result["total_profit"] / result["trade_count"] if result["trade_count"] > 0 else 0,
                    profit_yen,
                    result["average_hold_days"],
                    drawdown
                ])

                if best_result is None:

                    best_result = result
                    best_atr = atr
                    best_ma = (ma_short, ma_middle, ma_long)
                    best_rsi = (rsi_low, rsi_high)

                elif result["total_profit"] > best_result["total_profit"]:
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
