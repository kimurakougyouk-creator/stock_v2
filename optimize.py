from pathlib import Path

import pandas as pd
import yfinance as yf

from config import INTERVAL, PERIOD, RESULT_DIR
from optimizer import calculate_score, find_best_setting

TICKER = "7203.T"
OUTPUT_FILE = Path(RESULT_DIR) / "optimization_result.xlsx"


def main():
    print(f"最適化開始: {TICKER}")

    df = yf.download(
        TICKER,
        period=PERIOD,
        interval=INTERVAL,
        auto_adjust=True,
        progress=True,
    )

    if df.empty:
        raise RuntimeError(f"{TICKER} の株価データを取得できませんでした。")

    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    optimization = find_best_setting(df)
    best = optimization["result"]

    columns = [
        "ATR",
        "MA",
        "RSI",
        "勝率",
        "利益率",
        "取引回数",
        "1取引平均利益率",
        "純利益円",
        "最終資金",
        "手数料合計",
        "平均保有日数",
        "最大DD",
        "採用対象",
    ]

    results_df = pd.DataFrame(optimization["all_results"], columns=columns)

    def score_row(row):
        return calculate_score(
            {
                "total_profit": row["利益率"],
                "max_drawdown": row["最大DD"],
                "win_rate": row["勝率"],
                "trade_count": row["取引回数"],
            }
        )

    results_df["総合スコア"] = results_df.apply(score_row, axis=1)
    results_df = results_df.sort_values(
        ["採用対象", "総合スコア"],
        ascending=[False, False],
    ).reset_index(drop=True)
    results_df.insert(0, "順位", range(1, len(results_df) + 1))
    results_df.insert(1, "銘柄", TICKER)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        results_df.to_excel(writer, sheet_name="全結果", index=False)

        if best:
            best_df = pd.DataFrame(
                [
                    {
                        "銘柄": TICKER,
                        "ATR": optimization["atr"],
                        "MA": str(optimization["ma"]),
                        "RSI": str(optimization["rsi"]),
                        "勝率": best["win_rate"],
                        "利益率": best["total_profit"],
                        "最大DD": best["max_drawdown"],
                        "取引回数": best["trade_count"],
                        "純利益円": best["net_profit_yen"],
                        "最終資金": best["final_capital"],
                    }
                ]
            )
            best_df.to_excel(writer, sheet_name="最良設定", index=False)

    print("\n===== 最適化結果 =====")

    if best:
        print("ATR:", optimization["atr"])
        print("移動平均:", optimization["ma"])
        print("RSI:", optimization["rsi"])
        print("勝率:", f"{best['win_rate']:.2f}%")
        print("利益率:", f"{best['total_profit']:.2f}%")
        print("最大DD:", f"{best['max_drawdown']:.2f}%")
    else:
        print("最低取引回数を満たす設定はありませんでした。")

    print(f"全{len(results_df)}通りの結果を保存しました: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
