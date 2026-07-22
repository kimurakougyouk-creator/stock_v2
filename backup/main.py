import os
import pandas as pd
import yfinance as yf

from config import (
    PERIOD,
    INTERVAL,
    ATR_LIST,
    RSI_LIST,
    MA_LIST,
    EMAIL_ADDRESS,
    APP_PASSWORD,
)

from indicators import add_indicators
from strategy import create_buy_signal
from backtest import run_backtest
from mail import send_mail

def main():

    ticker_df = pd.read_csv("tickers.csv")

    tickers = ticker_df["Ticker"].tolist()

    summary = []
    atr_results = []
    buy_candidates = []

    if len(tickers) == 0:
        print("tickers.csv が空です。")
        return

    print("=" * 50)
    print("バックテスト開始")
    print("=" * 50)

    for ticker in tickers:

        print()

        print("=" * 50)
        print(f"処理中 : {ticker}")
        print("=" * 50)

        df = yf.download(
            ticker,

            period=PERIOD,
            interval=INTERVAL,
            auto_adjust=True
        )

        if df.empty:
            print("株価データを取得できませんでした。")
            continue

        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)

        best_result = None
        best_atr = None
        best_rsi = None
        best_ma = None

        for atr in ATR_LIST:

            print(f"ATR倍率 : {atr}")

            result = run_backtest(
                create_buy_signal(
                    add_indicators(df.copy())
                ),
                atr_multiplier=atr
            )
