"""Regression tests for Issue #285 Stage 2, risk_manager slice: moving
`calculate_position_size`/`calculate_open_position_risk`'s implementation
from the root-level `risk_manager.py` into
`ai_asset_platform.risk.risk_manager`, with `risk_manager.py` kept as a
backward-compatibility shim and `signal_runner.py` updated to import the
package implementation directly.

Behavior (arguments, return value, validation, lot-size/average-cost
math, defaults) is unchanged; only the import location moved. Other
root-level callers are unaffected since the shim preserves the same
public interface at the same path.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from ai_asset_platform.risk.risk_manager import (
    calculate_open_position_risk,
    calculate_position_size,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


def _load_root_risk_manager_module_fresh():
    """Load the root-level risk_manager.py directly by file path, bypassing
    sys.modules, so this assertion cannot be affected by any other test
    module's caching or fake-module injection elsewhere in this suite.
    """
    root_risk_manager_path = ROOT_DIR / "risk_manager.py"
    spec = importlib.util.spec_from_file_location(
        "_test_root_risk_manager_fresh", root_risk_manager_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_risk_manager_functions_importable_from_package():
    """The implementation lives in the package now."""
    assert callable(calculate_position_size)
    assert callable(calculate_open_position_risk)


def test_root_risk_manager_is_a_compatibility_shim():
    """`risk_manager`'s public interface still works, and is the *same*
    function objects as the package implementation -- not a
    reimplementation that could drift out of sync.
    """
    root_risk_manager = _load_root_risk_manager_module_fresh()

    assert (
        root_risk_manager.calculate_position_size is calculate_position_size
    )
    assert (
        root_risk_manager.calculate_open_position_risk
        is calculate_open_position_risk
    )


def test_root_risk_manager_has_no_duplicated_implementation():
    """The root shim must not re-implement the calculations -- it must be
    a thin re-export only.
    """
    text = (ROOT_DIR / "risk_manager.py").read_text(encoding="utf-8")

    assert "def calculate_position_size" not in text
    assert "def calculate_open_position_risk" not in text
    assert "from ai_asset_platform.risk.risk_manager import" in text


def test_package_import_does_not_require_repo_root_on_sys_path(tmp_path):
    """Isolated regression, offline (no network, no venv creation, no
    dependency reinstall): import `ai_asset_platform.risk.risk_manager` in
    a subprocess whose cwd is *not* the repo root and whose PYTHONPATH is
    set to `src/` only -- never the repo root itself, so root-level
    modules like `risk_manager.py` or `signal_runner.py` are never on the
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
        src_dir / "ai_asset_platform" / "risk" / "risk_manager.py"
    ).resolve()
    assert expected_module_path.is_file()

    env = dict(os.environ)
    # Only ever add src/ -- never the repo root -- so root-level modules
    # stay unreachable regardless of what else this interpreter already
    # has installed (e.g. an unrelated checkout's editable install, if
    # this test happens to run under a borrowed/shared venv).
    env["PYTHONPATH"] = str(src_dir)

    script = (
        "import ai_asset_platform.risk.risk_manager as m\n"
        "import sys\n"
        "assert 'risk_manager' not in sys.modules, ("
        "'root-level risk_manager must not have been imported')\n"
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
        "ai_asset_platform.risk.risk_manager resolved to a different file "
        f"than this checkout's own module: {resolved_module_path} "
        f"(expected {expected_module_path})"
    )


def test_signal_runner_does_not_import_from_root_risk_manager():
    """Static regression: `signal_runner.py` must import the package
    implementation directly (`ai_asset_platform.risk.risk_manager`), not
    the root-level compatibility shim (`from risk_manager import ...`).
    """
    signal_runner_path = ROOT_DIR / "signal_runner.py"
    text = signal_runner_path.read_text(encoding="utf-8")

    assert "from risk_manager import" not in text, (
        "signal_runner.py must not import from the root risk_manager shim"
    )
    assert "from ai_asset_platform.risk.risk_manager import" in text, (
        "signal_runner.py must import calculate_position_size/"
        "calculate_open_position_risk from the package implementation "
        "directly"
    )
