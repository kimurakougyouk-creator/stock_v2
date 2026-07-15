import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import smtplib

from openpyxl import Workbook
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================
# Gmail設定
# ==========================

EMAIL_ADDRESS = "あなたのGmail"
APP_PASSWORD = "アプリパスワード"

# ==========================
# バックテストする銘柄
# ==========================

tickers = pd.read_csv("tickers.csv")["Ticker"].tolist()

# ==========================
# パラメータ
# ==========================

ATR_LIST = [2.0, 2.5, 3.0]

RSI_LIST = [
    (50, 60),
    (55, 65),
    (60, 70)
]

INITIAL_CAPITAL = 1000000

# ==========================
# 結果保存
# ==========================

summary = []
buy_signals = []
sell_signals = []
atr_summary = []
rsi_summary = []
best_setting = []

# ==========================
# メイン処理
# ==========================

for ticker in tickers:

    print("=" * 50)
    print(ticker)
    print("=" * 50)

    df = yf.download(
        ticker,
        period="6mo",
        interval="1d",
        auto_adjust=True
    )

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if len(df) < 80:
        print("データ不足")
        continue

    # ==========================
    # 移動平均線
    # ==========================
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA25"] = df["Close"].rolling(25).mean()
    df["MA75"] = df["Close"].rolling(75).mean()

    # ==========================
    # RSI
    # ==========================
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    # ==========================
    # MACD
    # ==========================
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()

    df["MACD"] = ema12 - ema26
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    # ==========================
    # ATR
    # ==========================
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()

    # ==========================
    # 出来高20日平均
    # ==========================
    df["VOL20"] = df["Volume"].rolling(20).mean()

    print(f"{ticker} : 指標計算完了")

print("ここまで完成")
