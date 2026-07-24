import os

# ==========================
# Gmail設定
# ==========================

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "s.ossan777777@gmail.com")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# ==========================
# 運用モード
# ==========================

BROKER_MODE = os.getenv("BROKER_MODE", "dry_run")
DRY_RUN = BROKER_MODE.lower() in {"dry_run", "dry-run", "paper"}

# ==========================
# 初期資金
# ==========================

INITIAL_CAPITAL = 1_000_000

# ==========================
# ATR倍率候補
# ==========================

ATR_LIST = [
    2.0,
    2.5,
    3.0,
]

MA_LIST = [
    (5, 25, 75),
    (5, 20, 60),
    (10, 25, 75),
    (10, 30, 90),
    (20, 50, 100),
]

# ==========================
# RSI候補
# (RSI_LOW, RSI_HIGH)
# ==========================

RSI_LIST = [
    (50, 60),
    (55, 65),
    (60, 70),
]

# ==========================
# データ取得期間
# ==========================

PERIOD = "6mo"
INTERVAL = "1d"

# ==========================
# バックテスト対象
# ==========================

TICKER_FILE = "tickers.csv"

# ==========================
# 出力先
# ==========================

RESULT_DIR = "results"
EXCEL_FILE = "results/backtest_result.xlsx"
DRY_RUN_ORDER_FILE = os.getenv("DRY_RUN_ORDER_FILE", "results/dry_run_orders.json")
LOG_DIR = os.getenv("LOG_DIR", "results")
