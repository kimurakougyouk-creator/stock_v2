import pandas as pd
import yfinance as yf

from config import PERIOD, INTERVAL, EMAIL_ADDRESS, APP_PASSWORD
from indicators import add_indicators
from strategy import create_buy_signal
from backtest import run_backtest
from optimizer import find_best_setting
from report import save_report
from mail import send_mail

def main():

    summary = []

    ticker_df = pd.read_csv("tickers.csv")
    tickers = ticker_df["Ticker"].tolist()

    if len(tickers) == 0:
        print("tickers.csv が空です。")
        return

    print("バックテスト開始")

    for ticker in tickers:

        print(f"\n処理中: {ticker}")

        df = yf.download(
            ticker,
            period=PERIOD,
            interval=INTERVAL,
            auto_adjust=True
        )

        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)

        if df.empty:
            print("株価データを取得できませんでした。")
            continue

        df = add_indicators(df)

        best = find_best_setting(df)

        result = best["result"]

        print(f"最適ATR : {best['atr']}")
        print(f"最適MA  : {best['ma']}")
        print(f"最適RSI : {best['rsi']}")

        save_report(result["trades"], f"{ticker}_report.xlsx")

        print(
            f"売買回数: {result['trade_count']}  "
            f"勝率: {result['win_rate']:.1f}%  "
            f"利益率: {result['total_profit']:.2f}%"
        )

        summary.append([
            ticker,
            result["trade_count"],
            result["win_rate"],
            result["total_profit"],
            best["atr"],
            best["ma"],
            best["rsi"]
        ])

    summary_df = pd.DataFrame(
        summary,
        columns=[
            "Ticker",
            "TradeCount",
            "WinRate",
            "TotalProfit",
            "BestATR",
            "BestMA",
            "BestRSI"
        ]
    )

    summary_df.to_excel(
        "summary_report.xlsx",
        index=False
    )

    print("一覧を保存しました: summary_report.xlsx")

    subject = "バックテスト完了"
    body = "summary_report.xlsx を作成しました。"

    send_mail(
        EMAIL_ADDRESS,
        APP_PASSWORD,
        EMAIL_ADDRESS,
        subject,
        body
    )

if __name__ == "__main__":
    main()
