import pandas as pd
import yfinance as yf

from backtest import run_backtest
from report import save_report

tickers = pd.read_csv("tickers.csv")

ATR_LIST = [2.0, 2.5, 3.0] 

RSI_LIST = [
    (45, 75),
    (50, 70),
    (55, 65),
]

MA_SHORT_LIST = [5, 10]
MA_MID_LIST = [25, 50]
MA_LONG_LIST = [75, 100]

ATR_MULTIPLIER = 2.5

results = []

for _, row in tickers.iterrows():
    ticker = row["Ticker"]
    name = row["Name"]

    print(f"{ticker}  {name}")

    df = yf.download(
        ticker,
        period="6mo",
        interval="1d",
        auto_adjust=True
    )

    # MultiIndexを通常の列に変換
    df.columns = df.columns.get_level_values(0)

    # 移動平均
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA25"] = df["Close"].rolling(25).mean()
    df["MA75"] = df["Close"].rolling(75).mean()

    # ATR
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()

    # RSI
    delta = df["Close"].diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()

    df["MACD"] = ema12 - ema26
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # 出来高20日平均
    df["VOL20"] = df["Volume"].rolling(20).mean()

    best_result = None
    best_atr = None
    best_rsi = None

    for rsi_low, rsi_high in RSI_LIST:

        # 買いシグナル
        df["Buy"] = (
            (df["Close"] > df["MA25"]) &
            (df["MA25"] > df["MA75"]) &
            (df["MA5"] > df["MA25"]) &
            (df["RSI"] > rsi_low) &
            (df["RSI"] < rsi_high) &
            (df["MACD"] > df["Signal"]) &
            (df["Volume"] > df["VOL20"])
        )

        for atr in ATR_LIST:

            result = run_backtest(df, atr_multiplier=atr)

            print(f"\nRSI : {rsi_low}～{rsi_high}  ATR : {atr}")
            print(f"利益率 : {result['total_profit']:.2f}%")

            if (
                best_result is None
                or result["total_profit"] > best_result["total_profit"]
            ):
                best_result = result
                best_atr = atr
                best_rsi = f"{rsi_low}-{rsi_high}"

summary = pd.DataFrame(results)
print(summary)

summary.to_excel("summary_report.xlsx", index=False)
