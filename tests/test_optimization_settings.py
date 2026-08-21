from __future__ import annotations

import math

import pandas as pd

from optimization_settings import (
    DEFAULT_ATR,
    DEFAULT_MA,
    DEFAULT_RSI,
    BEST_SETTINGS_SHEET,
    load_optimized_settings,
)


def _write_settings(tmp_path, *, atr, ma="(5, 25, 75)", rsi="(60, 70)"):
    path = tmp_path / "optimization_result.xlsx"
    frame = pd.DataFrame(
        [
            {
                "銘柄": "7203.T",
                "ATR": atr,
                "MA": ma,
                "RSI": rsi,
            }
        ]
    )
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name=BEST_SETTINGS_SHEET, index=False)
    return path


def test_load_optimized_settings_replaces_nan_atr_with_default(tmp_path):
    path = _write_settings(tmp_path, atr=float("nan"))

    settings = load_optimized_settings(path)

    assert settings["7203.T"]["atr_multiplier"] == DEFAULT_ATR
    assert math.isfinite(settings["7203.T"]["atr_multiplier"])


def test_load_optimized_settings_replaces_non_positive_atr_with_default(tmp_path):
    path = _write_settings(tmp_path, atr=0)

    settings = load_optimized_settings(path)

    assert settings["7203.T"]["atr_multiplier"] == DEFAULT_ATR


def test_load_optimized_settings_replaces_invalid_ma_and_rsi_with_defaults(tmp_path):
    path = _write_settings(
        tmp_path,
        atr=2.5,
        ma="(5, None, 75)",
        rsi="(60, None)",
    )

    settings = load_optimized_settings(path)

    assert (
        settings["7203.T"]["ma_short"],
        settings["7203.T"]["ma_middle"],
        settings["7203.T"]["ma_long"],
    ) == DEFAULT_MA
    assert (
        settings["7203.T"]["rsi_low"],
        settings["7203.T"]["rsi_high"],
    ) == DEFAULT_RSI


def test_load_optimized_settings_preserves_valid_values(tmp_path):
    path = _write_settings(
        tmp_path,
        atr=2.5,
        ma="(10, 30, 90)",
        rsi="(55, 75)",
    )

    settings = load_optimized_settings(path)

    assert settings["7203.T"] == {
        "ma_short": 10,
        "ma_middle": 30,
        "ma_long": 90,
        "rsi_low": 55,
        "rsi_high": 75,
        "atr_multiplier": 2.5,
    }
