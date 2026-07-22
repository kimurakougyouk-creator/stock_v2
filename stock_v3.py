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

