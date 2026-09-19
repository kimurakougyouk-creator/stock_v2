"""Regression tests for Issue #285 Stage 2, indicators slice: moving
`add_indicators`'s implementation from the root-level `indicators.py` into
`ai_asset_platform.strategies.indicators`, with `indicators.py` kept as a
backward-compatibility shim and `signal_runner.py` updated to import the
package implementation directly.

Behavior (columns produced, custom MA window arguments) is unchanged; only
the import location moved. Other root-level callers (optimizer.py,
main_simple_step*.py, etc.) intentionally keep using the root shim -- this
slice is scoped to signal_runner.py only.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from ai_asset_platform.strategies.indicators import add_indicators

ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_root_indicators_module_fresh():
    """Load the root-level indicators.py directly by file path.

    Some other test modules in this suite (test_backtest_foundation.py,
    test_backtest_risk.py) install a fake `sys.modules["indicators"]`
    namespace via `sys.modules.setdefault(...)` as a collection-time side
    effect, to keep optimizer.py's backtest tests from depending on real
    indicator math. When those modules are collected first in the same
    pytest session, a plain `import indicators` here would silently pick up
    that unrelated fake instead of this checkout's real shim. Loading by
    explicit file path sidesteps that shared, order-dependent sys.modules
    state entirely.
    """
    root_indicators_path = ROOT_DIR / "indicators.py"
    spec = importlib.util.spec_from_file_location(
        "_test_root_indicators_fresh", root_indicators_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample_ohlcv(rows: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    base = pd.Series(range(rows), dtype=float) * 0.5 + 100.0

    return pd.DataFrame(
        {
            "Open": base,
            "High": base + 1.0,
            "Low": base - 1.0,
            "Close": base + 0.2,
            "Volume": pd.Series(range(rows), dtype=float) * 10 + 1000.0,
        },
        index=dates,
    )


def test_add_indicators_importable_from_package():
    """The implementation lives in the package now."""
    assert callable(add_indicators)


def test_root_indicators_is_a_compatibility_shim():
    """`indicators.add_indicators` still works, and is the *same* function
    object as the package implementation -- not a reimplementation that
    could drift out of sync.

    Loads the root shim by explicit file path (see
    `_load_root_indicators_module_fresh`) instead of `import indicators`,
    so this assertion is not order-dependent on other test modules' fake
    `sys.modules["indicators"]` injections elsewhere in this suite.
    """
    root_indicators = _load_root_indicators_module_fresh()
    from ai_asset_platform.strategies.indicators import (
        add_indicators as package_add_indicators,
    )

    assert root_indicators.add_indicators is package_add_indicators


def test_add_indicators_produces_expected_columns():
    df = _sample_ohlcv()

    result = add_indicators(df.copy())

    for column in ("MA5", "MA25", "MA75", "RSI", "MACD", "Signal", "ATR", "VOL20"):
        assert column in result.columns

    # Spot-check a couple of values against a direct pandas recomputation,
    # to confirm the formulas themselves are unchanged.
    expected_ma5 = df["Close"].rolling(5).mean()
    pd.testing.assert_series_equal(
        result["MA5"], expected_ma5, check_names=False
    )

    expected_vol20 = df["Volume"].rolling(20).mean()
    pd.testing.assert_series_equal(
        result["VOL20"], expected_vol20, check_names=False
    )


def test_add_indicators_custom_ma_windows_are_respected():
    df = _sample_ohlcv()

    result = add_indicators(df.copy(), ma_short=3, ma_middle=10, ma_long=20)

    pd.testing.assert_series_equal(
        result["MA5"],
        df["Close"].rolling(3).mean(),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        result["MA25"],
        df["Close"].rolling(10).mean(),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        result["MA75"],
        df["Close"].rolling(20).mean(),
        check_names=False,
    )


def test_package_import_does_not_require_repo_root_on_sys_path(tmp_path):
    """Isolated regression, offline (no network, no venv creation, no
    dependency reinstall): import `ai_asset_platform.strategies.indicators`
    in a subprocess whose cwd is *not* the repo root and whose PYTHONPATH is
    set to `src/` only -- never the repo root itself, so root-level modules
    like `indicators.py` or `signal_runner.py` are never on the import path
    at all. This proves resolution *correctness* (it resolves to this
    checkout's own package file, not the root-level shim, regardless of
    cwd), not resolution *mechanism*.

    Deliberately does NOT assert that removing PYTHONPATH breaks the
    import: in CI, `pip install -e .` already ran before this test suite,
    so `ai_asset_platform` resolves via the editable install regardless of
    PYTHONPATH -- asserting the opposite would be an environment-dependent
    false failure there, not a real regression in this checkout.
    """
    src_dir = ROOT_DIR / "src"
    expected_module_path = (
        src_dir / "ai_asset_platform" / "strategies" / "indicators.py"
    ).resolve()
    assert expected_module_path.is_file()

    env = dict(os.environ)
    # Only ever add src/ -- never the repo root -- so root-level modules
    # stay unreachable regardless of what else this interpreter already
    # has installed (e.g. an unrelated checkout's editable install, if
    # this test happens to run under a borrowed/shared venv).
    env["PYTHONPATH"] = str(src_dir)

    script = (
        "import ai_asset_platform.strategies.indicators as m\n"
        "import sys\n"
        "assert 'indicators' not in sys.modules, ("
        "'root-level indicators must not have been imported')\n"
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
        "ai_asset_platform.strategies.indicators resolved to a different "
        f"file than this checkout's own module: {resolved_module_path} "
        f"(expected {expected_module_path})"
    )


def test_signal_runner_does_not_import_from_root_indicators():
    """Static regression: `signal_runner.py` must import the package
    implementation directly (`ai_asset_platform.strategies.indicators`),
    not the root-level compatibility shim (`from indicators import ...`).
    """
    signal_runner_path = ROOT_DIR / "signal_runner.py"
    text = signal_runner_path.read_text(encoding="utf-8")

    assert "from indicators import" not in text, (
        "signal_runner.py must not import from the root indicators shim"
    )
    assert "from ai_asset_platform.strategies.indicators import" in text, (
        "signal_runner.py must import add_indicators from the package "
        "implementation directly"
    )
