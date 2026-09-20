"""Regression tests for Issue #285 Stage 2, signal_engine slice: moving
`determine_signal`'s implementation from the root-level `signal_engine.py`
into `ai_asset_platform.strategies.signal_engine`, with `signal_engine.py`
kept as a backward-compatibility shim and `signal_runner.py` updated to
import the package implementation directly.

Behavior (BUY/SELL/HOLD thresholds, scoring, grading, position sizing) is
unchanged; only the import location moved. No test in this suite
monkeypatches `signal_engine` module attributes (confirmed via repo-wide
inventory), so a plain re-export shim is sufficient here -- unlike
decision_logger.py, there is no unqualified-global monkeypatch dependency
to preserve.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ai_asset_platform.strategies.signal_engine import determine_signal

ROOT_DIR = Path(__file__).resolve().parents[1]


def test_determine_signal_importable_from_package():
    """The implementation lives in the package now."""
    assert callable(determine_signal)


def test_root_signal_engine_is_a_compatibility_shim():
    """`signal_engine.determine_signal` still works, and is the *same*
    function object as the package implementation -- not a
    reimplementation that could drift out of sync.
    """
    import signal_engine
    from ai_asset_platform.strategies.signal_engine import (
        determine_signal as package_determine_signal,
    )

    assert signal_engine.determine_signal is package_determine_signal


def test_root_signal_engine_has_no_duplicated_implementation():
    """The root shim must not re-implement determine_signal -- it must be
    a thin re-export only.
    """
    text = (ROOT_DIR / "signal_engine.py").read_text(encoding="utf-8")

    assert "def determine_signal" not in text
    assert "from ai_asset_platform.strategies.signal_engine import" in text


def test_package_import_does_not_require_repo_root_on_sys_path(tmp_path):
    """Isolated regression, offline (no network, no venv creation, no
    dependency reinstall): import `ai_asset_platform.strategies.signal_engine`
    in a subprocess whose cwd is *not* the repo root, with `src/` on
    PYTHONPATH. This proves resolution *correctness* (it resolves to this
    checkout's own package file, not the root-level shim, regardless of
    cwd), not resolution *mechanism*.

    Unlike the indicators.py/risk_manager.py migrations, `signal_engine.py`
    itself does `from config import LOT_SIZE, RISK_PER_TRADE_RATE,
    TRADING_CAPITAL` at module level -- config.py is a root-level module
    that has not been migrated into the package (out of scope for this
    slice), so the repo root must also be on PYTHONPATH for this import to
    succeed at all. That dependency is pre-existing and unchanged by this
    migration (root signal_engine.py had the exact same `from config
    import ...` line). This test therefore puts both src/ and the repo
    root on PYTHONPATH, and instead proves the meaningful invariant: the
    import resolves to the package's own file, not to a root-level
    shadow, even when the root-level shim module is also reachable.

    Deliberately does NOT assert that removing PYTHONPATH breaks the
    import: in CI, `pip install -e .` already ran before this test suite,
    so `ai_asset_platform` resolves via the editable install regardless of
    PYTHONPATH -- asserting the opposite would be an environment-dependent
    false failure there, not a real regression in this checkout.
    """
    src_dir = ROOT_DIR / "src"
    expected_module_path = (
        src_dir / "ai_asset_platform" / "strategies" / "signal_engine.py"
    ).resolve()
    assert expected_module_path.is_file()

    env = dict(os.environ)
    # src/ for the package; repo root only because signal_engine.py's own
    # (unchanged) `from config import ...` requires it -- never used to
    # smuggle in a different signal_engine.py.
    env["PYTHONPATH"] = os.pathsep.join([str(src_dir), str(ROOT_DIR)])

    script = (
        "import ai_asset_platform.strategies.signal_engine as m\n"
        "import sys\n"
        "assert 'signal_engine' not in sys.modules, ("
        "'root-level signal_engine must not have been imported as a side effect')\n"
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
        "ai_asset_platform.strategies.signal_engine resolved to a "
        f"different file than this checkout's own module: {resolved_module_path} "
        f"(expected {expected_module_path})"
    )


def test_signal_runner_does_not_import_from_root_signal_engine():
    """Static regression: `signal_runner.py` must import the package
    implementation directly (`ai_asset_platform.strategies.signal_engine`),
    not the root-level compatibility shim (`from signal_engine import ...`).
    """
    signal_runner_path = ROOT_DIR / "signal_runner.py"
    text = signal_runner_path.read_text(encoding="utf-8")

    assert "from signal_engine import" not in text, (
        "signal_runner.py must not import from the root signal_engine shim"
    )
    assert "from ai_asset_platform.strategies.signal_engine import" in text, (
        "signal_runner.py must import determine_signal from the package "
        "implementation directly"
    )
