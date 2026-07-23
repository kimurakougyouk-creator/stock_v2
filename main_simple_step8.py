import pandas as pd
import yfinance as yf

from config import PERIOD, INTERVAL, EMAIL_ADDRESS, APP_PASSWORD, INITIAL_CAPITAL
from indicators import add_indicators
from strategy import create_buy_signal
from backtest import run_backtest
from optimizer import find_best_setting, MIN_TRADES
from report import save_report
from mail import send_mail
from execution import DryRunBroker, record_dry_run_orders

def main():

    summary = []
    dry_run_broker = DryRunBroker()

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

        if result is None:
            print(f"最低売買回数({MIN_TRADES})を満たす設定がありませんでした。")
            continue

        print(f"最適ATR : {best['atr']}")
        print(f"最適MA  : {best['ma']}")
        print(f"最適RSI : {best['rsi']}")
        print(f"最適利益確定率 : {best['take_profit']}")
        print(f"最適損切り率 : {best['stop_loss']}")

        print("おすすめ設定")
        print(f"ATR = {best['atr']}")
        print(f"MA = {best['ma']}  RSI = {best['rsi']}")
        print(f"利益確定率 = {best['take_profit']}  損切り率 = {best['stop_loss']}")

        save_report(result["trades"], f"{ticker}_report.xlsx", result)
        dry_run_orders = record_dry_run_orders(
            ticker,
            result,
            dry_run_broker,
            available_cash=INITIAL_CAPITAL,
            dry_run=True,
        )
        print(f"dry-run模擬注文: {len(dry_run_orders)}件")

        settings_df = pd.DataFrame(
            all_results,
            columns=[
                "ATR",
                "MA",
                "RSI",
                "TakeProfit",
                "StopLoss",
                "WinRate",
                "TotalProfit",
                "TradeCount",
                "ProfitPerTrade",
                "ProfitYen",
                "FinalCapital",
                "TotalCommission",
                "AverageHoldDays",
                "MaxDrawdown",
                "Eligible",
            ]
        )

        settings_df = settings_df.sort_values("TotalProfit", ascending=False)
        settings_df.insert(0, "Rank", range(1, len(settings_df) + 1))
        settings_df.to_excel(f"{ticker}_settings.xlsx", index=False)

        print(
            f"売買回数: {result['trade_count']}  "
            f"勝率: {result['win_rate']:.1f}%  "
            f"利益率: {result['total_profit']:.2f}%  "
            f"最終資産: {result['final_capital']:.0f}円"
        )

        summary.append([
            ticker,
            result["trade_count"],
            result["win_rate"],
            result["total_profit"],
            best["atr"],
            best["ma"],
            best["rsi"],
            best["take_profit"],
            best["stop_loss"],
            result["final_capital"],
            result["net_profit_yen"],
            result["total_commission"]
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
            "BestRSI",
            "BestTakeProfit",
            "BestStopLoss",
            "FinalCapital",
            "NetProfitYen",
            "TotalCommission"
        ]
    )

    summary_df = summary_df.sort_values("TotalProfit", ascending=False)

    summary_df.insert(0, "Rank", range(1, len(summary_df) + 1))

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
