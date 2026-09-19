"""Regression tests for Issue #285 Stage 2, optimization_settings slice:
moving `load_optimized_settings`/`get_ticker_settings`'s implementation from
the root-level `optimization_settings.py` into
`ai_asset_platform.core.optimization_settings`, with `optimization_settings.py`
kept as a backward-compatibility shim and `signal_runner.py` updated to
import the package implementation directly.

Behavior (arguments, return value, defaults, Excel parsing) is unchanged;
only the import location moved.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from ai_asset_platform.core.optimization_settings import (
    BEST_SETTINGS_SHEET,
    DEFAULT_ATR,
    DEFAULT_MA,
    DEFAULT_RSI,
    get_ticker_settings,
    load_optimized_settings,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


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


def test_load_optimized_settings_importable_from_package():
    """The implementation lives in the package now."""
    assert callable(load_optimized_settings)
    assert callable(get_ticker_settings)


def test_root_optimization_settings_is_a_compatibility_shim():
    """`optimization_settings`'s public interface still works, and is the
    *same* objects as the package implementation -- not a reimplementation
    that could drift out of sync.
    """
    import optimization_settings
    from ai_asset_platform.core.optimization_settings import (
        BEST_SETTINGS_SHEET as package_best_settings_sheet,
        DEFAULT_ATR as package_default_atr,
        DEFAULT_MA as package_default_ma,
        DEFAULT_RSI as package_default_rsi,
        OPTIMIZATION_FILE as package_optimization_file,
        get_ticker_settings as package_get_ticker_settings,
        load_optimized_settings as package_load_optimized_settings,
    )

    assert (
        optimization_settings.load_optimized_settings
        is package_load_optimized_settings
    )
    assert (
        optimization_settings.get_ticker_settings
        is package_get_ticker_settings
    )
    assert optimization_settings.DEFAULT_MA == package_default_ma
    assert optimization_settings.DEFAULT_RSI == package_default_rsi
    assert optimization_settings.DEFAULT_ATR == package_default_atr
    assert optimization_settings.OPTIMIZATION_FILE == package_optimization_file
    assert (
        optimization_settings.BEST_SETTINGS_SHEET
        == package_best_settings_sheet
    )


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


def test_get_ticker_settings_returns_defaults_when_missing():
    defaults = get_ticker_settings("9999.T", {})

    assert defaults == {
        "ma_short": DEFAULT_MA[0],
        "ma_middle": DEFAULT_MA[1],
        "ma_long": DEFAULT_MA[2],
        "rsi_low": DEFAULT_RSI[0],
        "rsi_high": DEFAULT_RSI[1],
        "atr_multiplier": DEFAULT_ATR,
    }


def test_package_import_does_not_require_repo_root_on_sys_path(tmp_path):
    """Isolated regression, offline (no network, no venv creation, no
    dependency reinstall): import
    `ai_asset_platform.core.optimization_settings` in a subprocess whose
    cwd is *not* the repo root and whose PYTHONPATH is set to `src/` only --
    never the repo root itself, so root-level modules like
    `optimization_settings.py` or `signal_runner.py` are never on the
    import path at all. This proves resolution *correctness* (it resolves
    to this checkout's own package file, not the root-level shim,
    regardless of cwd), not resolution *mechanism*.

    Deliberately does NOT assert that removing PYTHONPATH breaks the
    import: in CI, `pip install -e .` already ran before this test suite,
    so `ai_asset_platform` resolves via the editable install regardless of
    PYTHONPATH -- asserting the opposite would be an environment-dependent
    false failure there, not a real regression in this checkout.
    """
    src_dir = ROOT_DIR / "src"
    expected_module_path = (
        src_dir / "ai_asset_platform" / "core" / "optimization_settings.py"
    ).resolve()
    assert expected_module_path.is_file()

    env = dict(os.environ)
    # Only ever add src/ -- never the repo root -- so root-level modules
    # stay unreachable regardless of what else this interpreter already
    # has installed (e.g. an unrelated checkout's editable install, if
    # this test happens to run under a borrowed/shared venv).
    env["PYTHONPATH"] = str(src_dir)

    script = (
        "import ai_asset_platform.core.optimization_settings as m\n"
        "import sys\n"
        "assert 'optimization_settings' not in sys.modules, ("
        "'root-level optimization_settings must not have been imported')\n"
        "print(m.__file__)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"isolated package import failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    resolved_module_path = Path(result.stdout.strip()).resolve()
    assert resolved_module_path == expected_module_path, (
        "ai_asset_platform.core.optimization_settings resolved to a "
        f"different file than this checkout's own module: {resolved_module_path} "
        f"(expected {expected_module_path})"
    )


def test_signal_runner_does_not_import_from_root_optimization_settings():
    """Static regression: `signal_runner.py` must import the package
    implementation directly (`ai_asset_platform.core.optimization_settings`),
    not the root-level compatibility shim (`from optimization_settings import ...`).
    """
    signal_runner_path = ROOT_DIR / "signal_runner.py"
    text = signal_runner_path.read_text(encoding="utf-8")

    assert "from optimization_settings import" not in text, (
        "signal_runner.py must not import from the root optimization_settings shim"
    )
    assert "from ai_asset_platform.core.optimization_settings import" in text, (
        "signal_runner.py must import get_ticker_settings/load_optimized_settings "
        "from the package implementation directly"
    )
