from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_MA = (5, 25, 75)
DEFAULT_RSI = (60, 70)
DEFAULT_ATR = 2.0

OPTIMIZATION_FILE = Path("results/optimization_result.xlsx")
BEST_SETTINGS_SHEET = "銘柄別最良設定"


def _parse_tuple(value: Any, default: tuple[int, ...]) -> tuple[int, ...]:
    """Excel内の '(5, 20, 60)' などを安全にタプルへ変換する。"""
    if isinstance(value, tuple):
        parsed = value
    elif isinstance(value, list):
        parsed = tuple(value)
    elif isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return default
    else:
        return default

    if not isinstance(parsed, (tuple, list)):
        return default

    try:
        return tuple(int(number) for number in parsed)
    except (TypeError, ValueError):
        return default


def load_optimized_settings(
    path: str | Path = OPTIMIZATION_FILE,
) -> dict[str, dict[str, Any]]:
    """最適化結果を銘柄別の設定辞書として読み込む。"""
    file_path = Path(path)

    if not file_path.exists():
        return {}

    try:
        df = pd.read_excel(file_path, sheet_name=BEST_SETTINGS_SHEET)
    except (ValueError, OSError):
        return {}

    required_columns = {"銘柄", "ATR", "MA", "RSI"}
    if not required_columns.issubset(df.columns):
        return {}

    settings: dict[str, dict[str, Any]] = {}

    for _, row in df.iterrows():
        ticker = str(row["銘柄"]).strip()
        if not ticker or ticker.lower() == "nan":
            continue

        ma = _parse_tuple(row["MA"], DEFAULT_MA)
        rsi = _parse_tuple(row["RSI"], DEFAULT_RSI)

        if len(ma) != 3:
            ma = DEFAULT_MA
        if len(rsi) != 2:
            rsi = DEFAULT_RSI

        try:
            atr_multiplier = float(row["ATR"])
        except (TypeError, ValueError):
            atr_multiplier = DEFAULT_ATR

        settings[ticker] = {
            "ma_short": ma[0],
            "ma_middle": ma[1],
            "ma_long": ma[2],
            "rsi_low": rsi[0],
            "rsi_high": rsi[1],
            "atr_multiplier": atr_multiplier,
        }

    return settings


def get_ticker_settings(
    ticker: str,
    all_settings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """指定銘柄の設定を返す。設定がなければ安全な初期値を返す。"""
    if all_settings is None:
        all_settings = load_optimized_settings()

    return all_settings.get(
        ticker,
        {
            "ma_short": DEFAULT_MA[0],
            "ma_middle": DEFAULT_MA[1],
            "ma_long": DEFAULT_MA[2],
            "rsi_low": DEFAULT_RSI[0],
            "rsi_high": DEFAULT_RSI[1],
            "atr_multiplier": DEFAULT_ATR,
        },
    )
