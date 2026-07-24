# ==========================
# Gmail設定
# ==========================

import os
from pathlib import Path


def _resolve_env_path(env_file: str | None = None) -> Path | None:
    candidates = []
    if env_file:
        candidates.append(Path(env_file))

    cwd_env = Path.cwd() / ".env"
    repo_env = Path(__file__).resolve().parent / ".env"
    candidates.extend([cwd_env, repo_env])

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def _read_env_value(env_file: Path | None, key: str) -> str:
    if env_file is None:
        return os.getenv(key, "")

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export "):].strip()

        if "=" not in line:
            continue

        parsed_key, value = line.split("=", 1)
        if parsed_key.strip() != key:
            continue

        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value

    return os.getenv(key, "")


def _get_mail_setting(key: str) -> str:
    env_value = os.getenv(key, "")
    if env_value:
        return env_value

    env_path = _resolve_env_path()
    return _read_env_value(env_path, key)


EMAIL_ADDRESS = _get_mail_setting("EMAIL_ADDRESS")
APP_PASSWORD = _get_mail_setting("APP_PASSWORD")

# ==========================
# 初期資金
# ==========================

INITIAL_CAPITAL = 1_000_000

# ==========================
# バックテスト条件
# ==========================

COMMISSION_RATE = 0.001
SLIPPAGE_RATE = 0.001
STOP_LOSS_RATE = 0.03
TAKE_PROFIT_RATE = 0.06
MIN_TRADES = 5

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

PERIOD = "5y"
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
