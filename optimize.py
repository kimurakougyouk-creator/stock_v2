from pathlib import Path

import pandas as pd
import yfinance as yf

from config import INTERVAL, PERIOD, RESULT_DIR, TICKER_FILE
from optimizer import calculate_score, find_best_setting

OUTPUT_FILE = Path(RESULT_DIR) / "optimization_result.xlsx"

RESULT_COLUMNS = [
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


def calculate_result_score(row):
    return calculate_score(
        {
            "total_profit": row["利益率"],
            "max_drawdown": row["最大DD"],
            "win_rate": row["勝率"],
            "trade_count": row["取引回数"],
        }
    )


def download_stock_data(ticker):
    df = yf.download(
        ticker,
        period=PERIOD,
        interval=INTERVAL,
        auto_adjust=True,
        progress=True,
    )

    if df.empty:
        raise RuntimeError("株価データを取得できませんでした。")

    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    return df


def optimize_ticker(ticker, name):
    print()
    print("=" * 60)
    print(f"最適化開始: {ticker}（{name}）")
    print("=" * 60)

    df = download_stock_data(ticker)
    optimization = find_best_setting(df)
    best = optimization["result"]

    all_results_df = pd.DataFrame(
        optimization["all_results"],
        columns=RESULT_COLUMNS,
    )

    all_results_df["総合スコア"] = all_results_df.apply(
        calculate_result_score,
        axis=1,
    )
    all_results_df = all_results_df.sort_values(
        ["採用対象", "総合スコア"],
        ascending=[False, False],
    ).reset_index(drop=True)

    all_results_df.insert(0, "銘柄名", name)
    all_results_df.insert(0, "銘柄", ticker)

    if best is None:
        print(f"{ticker}: 最低取引回数を満たす設定がありませんでした。")
        return None, all_results_df

    best_summary = {
        "銘柄": ticker,
        "銘柄名": name,
        "ATR": optimization["atr"],
        "MA": str(optimization["ma"]),
        "RSI": str(optimization["rsi"]),
        "勝率": best["win_rate"],
        "利益率": best["total_profit"],
        "最大DD": best["max_drawdown"],
        "取引回数": best["trade_count"],
        "純利益円": best["net_profit_yen"],
        "最終資金": best["final_capital"],
        "手数料合計": best["total_commission"],
        "平均保有日数": best["average_hold_days"],
        "総合スコア": calculate_score(best),
    }

    print(f"{ticker}: 最適化完了")
    print(f"  ATR: {optimization['atr']}")
    print(f"  移動平均: {optimization['ma']}")
    print(f"  RSI: {optimization['rsi']}")
    print(f"  勝率: {best['win_rate']:.2f}%")
    print(f"  利益率: {best['total_profit']:.2f}%")
    print(f"  最大DD: {best['max_drawdown']:.2f}%")

    return best_summary, all_results_df


def main():
    ticker_path = Path(TICKER_FILE)

    if not ticker_path.exists():
        raise FileNotFoundError(
            f"銘柄ファイルが見つかりません: {ticker_path}"
        )

    ticker_df = pd.read_csv(ticker_path)

    required_columns = {"Ticker", "Name"}
    missing_columns = required_columns - set(ticker_df.columns)

    if missing_columns:
        raise ValueError(
            "tickers.csvに必要な列がありません: "
            + ", ".join(sorted(missing_columns))
        )

    ticker_df = ticker_df.dropna(subset=["Ticker"]).copy()
    ticker_df["Ticker"] = ticker_df["Ticker"].astype(str).str.strip()
    ticker_df["Name"] = ticker_df["Name"].fillna("").astype(str).str.strip()
    ticker_df = ticker_df[ticker_df["Ticker"] != ""]

    best_results = []
    all_results = []
    errors = []

    total_tickers = len(ticker_df)

    print(f"一括最適化を開始します: 全{total_tickers}銘柄")

    for number, row in enumerate(ticker_df.itertuples(index=False), start=1):
        ticker = row.Ticker
        name = row.Name

        print(f"\n進捗: {number}/{total_tickers}")

        try:
            best_summary, results_df = optimize_ticker(ticker, name)

            if best_summary is not None:
                best_results.append(best_summary)

            all_results.append(results_df)

        except Exception as error:
            print(f"{ticker}: エラー - {error}")
            errors.append(
                {
                    "銘柄": ticker,
                    "銘柄名": name,
                    "エラー内容": str(error),
                }
            )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    best_df = pd.DataFrame(best_results)

    if not best_df.empty:
        best_df = best_df.sort_values(
            "総合スコア",
            ascending=False,
        ).reset_index(drop=True)
        best_df.insert(0, "順位", range(1, len(best_df) + 1))

    if all_results:
        all_results_df = pd.concat(all_results, ignore_index=True)
        all_results_df = all_results_df.sort_values(
            ["銘柄", "採用対象", "総合スコア"],
            ascending=[True, False, False],
        ).reset_index(drop=True)
    else:
        all_results_df = pd.DataFrame()

    errors_df = pd.DataFrame(errors)

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        best_df.to_excel(
            writer,
            sheet_name="銘柄別最良設定",
            index=False,
        )
        all_results_df.to_excel(
            writer,
            sheet_name="全最適化結果",
            index=False,
        )

        if not errors_df.empty:
            errors_df.to_excel(
                writer,
                sheet_name="取得失敗",
                index=False,
            )

    print()
    print("=" * 60)
    print("一括最適化が完了しました")
    print(f"成功: {len(best_results)}銘柄")
    print(f"失敗: {len(errors)}銘柄")
    print(f"保存先: {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
