"""Regression tests for Issue #285 Stage 2, decision_logger slice: moving
`log_decision`'s implementation from the root-level `decision_logger.py`
into `ai_asset_platform.reports.decision_logger`, with `decision_logger.py`
kept as a backward-compatibility shim and `signal_runner.py` updated to
import the package implementation directly.

`decision_logger.py` uses a `sys.modules` aliasing shim (rather than a
plain `from ... import` re-export) because `log_decision` and
`_upgrade_existing_log` reference `LOG_FILE` as an unqualified module
global inside their function bodies, not as a parameter.
`tests/test_decision_logger.py` monkeypatches `decision_logger.LOG_FILE`
to redirect writes into a tmp_path; a plain re-export would create a
separate `LOG_FILE` binding on the shim that `log_decision` never reads,
silently falling through to the real `results/decision_log.csv` path.
Aliasing `sys.modules["decision_logger"]` to the package module object
keeps the shim and the package sharing one namespace, so that
monkeypatch pattern keeps working unmodified.

Behavior (CSV field names/order, encoding, timestamp format, Ordered
YES/NO, number rounding, schema-upgrade logic, append/header behavior) is
unchanged; only the import location moved.
"""
from __future__ import annotations

import csv
import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def test_log_decision_importable_from_package():
    """The implementation lives in the package now."""
    from ai_asset_platform.reports.decision_logger import log_decision

    assert callable(log_decision)


def test_root_decision_logger_is_the_same_module_as_the_package():
    """`decision_logger` (root) and `ai_asset_platform.reports.decision_logger`
    (package) must be the *same* module object -- not two separate
    namespaces that could drift out of sync -- so that
    `log_decision`/`FIELDNAMES`/`LOG_FILE` are identical either way it is
    imported, and monkeypatching one is visible through the other.
    """
    import decision_logger
    import ai_asset_platform.reports.decision_logger as package_decision_logger

    assert decision_logger is package_decision_logger
    assert decision_logger.log_decision is package_decision_logger.log_decision
    assert decision_logger.LOG_FILE is package_decision_logger.LOG_FILE
    assert decision_logger.FIELDNAMES is package_decision_logger.FIELDNAMES


def test_log_file_and_fieldnames_compatible():
    from ai_asset_platform.reports.decision_logger import (
        FIELDNAMES,
        LOG_FILE,
    )

    assert LOG_FILE == Path("results") / "decision_log.csv"
    assert FIELDNAMES == [
        "Timestamp",
        "Ticker",
        "FinalSignal",
        "Ordered",
        "Reason",
        "AISignal",
        "AIConfidence",
        "TechnicalSignal",
        "Price",
        "Score",
        "Grade",
        "RSI",
        "ATR",
        "MAShort",
        "MAMiddle",
        "MALong",
        "AIScore",
        "AIProvider",
    ]


def test_root_decision_logger_has_no_duplicated_implementation():
    """The root shim must not re-implement `log_decision` -- it must
    delegate to the package entirely.
    """
    text = (ROOT_DIR / "decision_logger.py").read_text(encoding="utf-8")

    assert "def log_decision" not in text
    assert "def _upgrade_existing_log" not in text
    assert "ai_asset_platform.reports" in text


def test_signal_runner_does_not_import_from_root_decision_logger():
    """Static regression: `signal_runner.py` must import the package
    implementation directly (`ai_asset_platform.reports.decision_logger`),
    not the root-level compatibility shim (`from decision_logger import ...`).
    """
    signal_runner_path = ROOT_DIR / "signal_runner.py"
    text = signal_runner_path.read_text(encoding="utf-8")

    assert "from decision_logger import" not in text, (
        "signal_runner.py must not import from the root decision_logger shim"
    )
    assert "from ai_asset_platform.reports.decision_logger import" in text, (
        "signal_runner.py must import log_decision from the package "
        "implementation directly"
    )


def test_package_import_does_not_require_repo_root_on_sys_path(tmp_path):
    """Isolated regression, offline (no network, no venv creation, no
    dependency reinstall): import `ai_asset_platform.reports.decision_logger`
    in a subprocess whose cwd is *not* the repo root and whose PYTHONPATH is
    set to `src/` only -- never the repo root itself, so root-level
    modules like `decision_logger.py` or `signal_runner.py` are never on
    the import path at all. This proves resolution *correctness* (it
    resolves to this checkout's own package file, not the root-level
    shim, regardless of cwd), not resolution *mechanism*.

    Deliberately does NOT assert that removing PYTHONPATH breaks the
    import: in CI, `pip install -e .` already ran before this test suite,
    so `ai_asset_platform` resolves via the editable install regardless of
    PYTHONPATH -- asserting the opposite would be an environment-dependent
    false failure there, not a real regression in this checkout.
    """
    src_dir = ROOT_DIR / "src"
    expected_module_path = (
        src_dir / "ai_asset_platform" / "reports" / "decision_logger.py"
    ).resolve()
    assert expected_module_path.is_file()

    env = dict(os.environ)
    # Only ever add src/ -- never the repo root -- so root-level modules
    # stay unreachable regardless of what else this interpreter already
    # has installed (e.g. an unrelated checkout's editable install, if
    # this test happens to run under a borrowed/shared venv).
    env["PYTHONPATH"] = str(src_dir)

    script = (
        "import ai_asset_platform.reports.decision_logger as m\n"
        "import sys\n"
        "assert 'decision_logger' not in sys.modules, ("
        "'root-level decision_logger must not have been imported')\n"
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
        "ai_asset_platform.reports.decision_logger resolved to a different "
        f"file than this checkout's own module: {resolved_module_path} "
        f"(expected {expected_module_path})"
    )


def test_importing_package_module_does_not_write_any_file(tmp_path, monkeypatch):
    """Import-time side-effect absence: merely importing the package
    module (fresh, uncached) must not create/touch any CSV file. Runs in
    an isolated cwd so this can never touch the real repo's results/.
    """
    monkeypatch.chdir(tmp_path)

    for name in (
        "decision_logger",
        "ai_asset_platform.reports.decision_logger",
    ):
        sys.modules.pop(name, None)

    importlib.import_module("ai_asset_platform.reports.decision_logger")

    assert not (tmp_path / "results").exists()
    assert not (tmp_path / "results" / "decision_log.csv").exists()


def test_monkeypatched_root_log_file_is_honored_by_log_decision(
    tmp_path, monkeypatch
):
    """The exact pattern used by tests/test_decision_logger.py: patch
    `decision_logger.LOG_FILE` on the root import and confirm
    `log_decision` actually writes there (not to the real results/ path),
    proving the sys.modules aliasing shim keeps this working.
    """
    import decision_logger

    log_file = tmp_path / "results" / "decision_log.csv"
    monkeypatch.setattr(decision_logger, "LOG_FILE", log_file)

    decision_logger.log_decision(
        ticker="TEST.T",
        final_signal="BUY",
        ordered=True,
        reason="package migration regression",
        ai_signal="BUY",
        ai_confidence=90.0,
        technical_signal="BUY",
    )

    assert log_file.exists()

    with log_file.open("r", newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 1
    assert rows[0]["Ticker"] == "TEST.T"
