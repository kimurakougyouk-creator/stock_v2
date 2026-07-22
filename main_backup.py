import pandas as pd
import os
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
from backtest import run_bimport pandas as pd
import os
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
from mail import send_mailacktest
from mail import send_mail

from report import save_report


def main():

    ticker_df = pd.read_csv("tickers.csv")

    tickers = ticker_df["Ticker"].tolist()

    summary = []
    atr_results = []
    buy_candidates = []

    if len(tickers) == 0:
        print("tickers.csv が空です。")
        return

    for ticker in tickers:

        print(f"\n処理中 : {ticker}")

        best_result = None
        best_atr = None
        best_rsi = None
        best_ma = None

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

        for atr in ATR_LIST:

            print(f"\n==========")
            print(f"バックテスト開始 : {ticker}  ATR={atr}")
            print("==========")

            for ma_short, ma_middle, ma_long in MA_LIST:

                df_ma = add_indicators(
                    df.copy(),
                    ma_short,
                    ma_middle,
                    ma_long
                )
