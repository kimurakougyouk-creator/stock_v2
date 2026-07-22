import pandas as pd
import yfinance as yf

from config import PERIOD, INTERVAL, EMAIL_ADDRESS, APP_PASSWORD
from indicators import add_indicators
from strategy import create_buy_signal
from backtest import run_backtest
from optimizer import find_best_setting
from report import save_report
from mail import send_mail
import matplotlib.pyplot as plt

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

        all_results = best["all_results"]

        result = best["result"]

        print(f"最適ATR : {best['atr']}")
        print(f"最適MA  : {best['ma']}")
        print(f"最適RSI : {best['rsi']}")

        print("おすすめ設定")
        print(f"ATR = {best['atr']}")
        print(f"MA = {best['ma']}  RSI = {best['rsi']}")

        save_report(result["trades"], f"{ticker}_report.xlsx")

    # 売買ポイント用データ
    buy_dates = [t["buy_date"] for t in result["trades"]]
    buy_prices = [t["buy_price"] for t in result["trades"]]

    sell_dates = [t["sell_date"] for t in result["trades"]]
    sell_prices = [t["sell_price"] for t in result["trades"]]

    plt.figure(figsize=(12, 6))
    plt.plot(df.index, df["Close"], label="Close")

    plt.scatter(
        buy_dates,
        buy_prices,
        marker="^",
        s=120,
        label="Buy"
    )

    plt.scatter(
        sell_dates,
        sell_prices,
        marker="v",
        s=120,
        label="Sell"
    )

    plt.title(f"{ticker} Buy / Sell")
    plt.legend()
    plt.grid(True)

    plt.savefig(f"{ticker}_signal.png")
    plt.close()

    print(f"売買チャート保存: {ticker}_signal.png")

    asset = result["asset_curve"]

    if len(asset) > 0:
        dates = [x["date"] for x in asset]
        capitals = [x["capital"] for x in asset]

        plt.figure(figsize=(10,5))
        plt.plot(dates, capitals)
        plt.title(f"{ticker} Asset Curve")
        plt.xlabel("Date")
        plt.ylabel("Capital")
        plt.grid(True)

        plt.savefig(f"{ticker}_asset_curve.png")
        plt.close()

        print(f"資産曲線保存: {ticker}_asset_curve.png")

    settings_df = pd.DataFrame(
            all_results,
            columns=[
                "ATR",
                "MA",
                "RSI",
                "WinRate",
                "TotalProfit",
                "TradeCount",
                "AverageProfit",
                "ProfitYen",
                "AverageHoldDays",
                "MaxDrawdown"
            ]
       )

    settings_df["AverageProfit"] = settings_df["AverageProfit"].map(lambda x: f"{x:.2f}%")
    settings_df["MaxDrawdown"] = settings_df["MaxDrawdown"].map(lambda x: f"{x:.2f}%")
    settings_df = settings_df.sort_values("TotalProfit", ascending=False)
    settings_df.insert(0, "Rank", range(1, len(settings_df) + 1))
    settings_df["ProfitYen"] = settings_df["ProfitYen"].round(0).astype(int)
    settings_df["ProfitYen"] = settings_df["ProfitYen"].map(lambda x: f"{x:,}円")

        settings_df["AverageHoldDays"] = settings_df["AverageHoldDays"].round().astype(int).astype(str) + "日"
        settings_df.to_excel(f"{ticker}_settings.xlsx", index=False)

        print(
            f"売買回数: {result['trade_count']}  "
            f"勝率: {result['win_rate']:.1f}%  "
            f"利益率: {result['total_profit']:.2f}%"
        )

        profit_yen = int(result["total_profit"] / 100 * 1_000_000)

    summary.append([
        ticker,
        result["trade_count"],
        result["win_rate"],
        result["total_profit"],
        profit_yen,
        result["max_drawdown"],
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
            "ProfitYen",
            "MaxDrawdown",
            "BestATR",
            "BestMA",
            "BestRSI"
        ]
    )

    summary_df = summary_df.sort_values("TotalProfit", ascending=False)

    summary_df.insert(0, "Rank", range(1, len(summary_df) + 1))

    summary_df["ProfitYen"] = summary_df["ProfitYen"].map(lambda x: f"{x:,}円")
    summary_df = summary_df.sort_values("TotalProfit", ascending=False)

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
