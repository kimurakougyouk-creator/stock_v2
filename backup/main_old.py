    for ticker in tickers:

        company_name = ticker_df.loc[
            ticker_df["Ticker"] == ticker, "Name"
        ].values[0]

        best_result = None    for ticker in tickers:

        company_name = ticker_df.loc[
            ticker_df["Ticker"] == ticker, "Name"
        ].values[0]

        best_result = Noneimport pandas as pd
import os
import yfinance as yf
import json

from config import PERIOD, INTERVAL, EXCEL_FILE, ATR_LIST, RSI_LIST, MA_LIST
from indicators import add_indicators
from strategy import create_buy_signal
from backtest import run_backtest
from report import save_report

from mail import send_mail
from config import EMAIL_ADDRESS, APP_PASSWORD

def main():

    ticker_df = pd.read_csv("tickers.csv")

    tickers = ticker_df["Ticker"].tolist()

    summary = []
    atr_results = []
    buy_candidates = []

    signal_file = "results/buy_candidates.json"

    previous_candidates = []

    if os.path.exists(signal_file):
        with open(signal_file, "r") as f:
            previous_candidates = json.load(f)

    if len(tickers) == 0:
        print("tickers.csv が空です。")
        return

    for ticker in tickers:

        company_name = ticker_df.loc[
            ticker_df["Ticker"] == ticker, "Name"
        ].values[0]

        best_result = None

        for atr in ATR_LIST:

            print(f"\n==========")
            print(f"バックテスト開始 : {ticker}  ATR={atr}")
            print("==========")

            df = yf.download(
                ticker,
                period=PERIOD,
                interval=INTERVAL,
                auto_adjust=True
            )

            # MultiIndex対策
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = df.columns.get_level_values(0)

            if df.empty:
                print("株価データを取得できませんでした。")
                continue


            for ma_short, ma_middle, ma_long in MA_LIST:

                df_ma = add_indicators(df.copy(), ma_short, ma_middle, ma_long)

                for rsi_low, rsi_high in RSI_LIST:

                    df2 = create_buy_signal(
                        df_ma.copy(),
                        rsi_low=rsi_low,
                        rsi_high=rsi_high
                    )

                    result = run_backtest(df2, atr_multiplier=atr)


                    if (
                        best_result is None
                        or result["total_profit"] > best_result["total_profit"]
                    ):
                        best_result = result
                        best_atr = atr
                        best_rsi = (rsi_low, rsi_high)
                        best_ma = (ma_short, ma_middle, ma_long)

                    atr_results.append({
                           "Ticker": ticker,
                           "ATR": atr,
                           "RSI_LOW": rsi_low,
                           "RSI_HIGH": rsi_high,
                           "MA": f"{ma_short}-{ma_middle}-{ma_long}",
                           "TradeCount": result["trade_count"],
                           "WinRate": result["win_rate"],
                           "TotalProfit": result["total_profit"]
                    })


        print(f"採用ATR倍率 : {best_atr}")
        print(f"採用RSI : {best_rsi}")
        print(f"採用MA : {best_ma}")

        print(
            f"取引回数: {best_result['trade_count']}  "
            f"勝率: {best_result['win_rate']:.1f}%  "
            f"総利益率: {best_result['total_profit']:.2f}%"
        )

    summary.append({
        "Ticker": ticker,
        "TradeCount": best_result["trade_count"],
        "WinRate": best_result["win_rate"],
        "TotalProfit": best_result["total_profit"],
        "BestATR": best_atr,
        "BestRSI": f"{best_rsi[0]}-{best_rsi[1]}",
        "BestMA": f"{best_ma[0]}-{best_ma[1]}-{best_ma[2]}",
    })

    # 最適条件でもう一度シグナル作成
    best_df = add_indicators(
        df.copy(),
        best_ma[0],
        best_ma[1],
        best_ma[2]
    )

    best_df = create_buy_signal(
        best_df,
        rsi_low=best_rsi[0],
        rsi_high=best_rsi[1]
    )

    # 今日が買いシグナルなら候補に追加
    if best_df["Buy"].iloc[-1]:
        buy_candidates.append(ticker)

    summary_df = pd.DataFrame(summary)
    atr_df = pd.DataFrame(atr_results)

    os.makedirs("results", exist_ok=True)

    summary_df.to_excel(
       "results/summary.xlsx",
        index=False
    )

    atr_df.to_excel(
        "results/atr_comparison.xlsx",
         index=False
    )

    print("\n========================")
    print("summary.xlsx を保存しました")
    print("========================")

    body = "【今日の買い候補】\n\n"

    new_candidates = [
        x for x in buy_candidates
        if x not in previous_candidates
    ]

    body += "★★ 新しく買いシグナルが出た銘柄 ★★\n"

    if new_candidates:
    for ticker in new_candidates:
        name = ticker_df.loc[ticker_df["Ticker"] == ticker, "Name"].values[0]
        body += f"{ticker}  {name}\n"
    else:
        body += "新規銘柄なし"

    body += "\n\n====================\n\n"

    if buy_candidates:
        body += "\n".join(buy_candidates)
    else:
        body += "該当銘柄なし"

    new_candidates = [
        x for x in buy_candidates
        if x not in previous_candidates
    ]

    body += "\n\n====================\n\n"

    body += "バックテスト結果\n\n"

    body += summary_df.to_string(index=False)

    send_mail(
        EMAIL_ADDRESS,
        APP_PASSWORD,
        EMAIL_ADDRESS,
        "バックテスト結果",
        body
    )

    with open(signal_file, "w") as f:
        json.dump(buy_candidates, f)

if __name__ == "__main__":
    main()
  
