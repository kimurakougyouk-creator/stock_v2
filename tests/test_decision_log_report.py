"""Regression tests for Issue #285 Stage 2, decision_log_report slice:
moving `generate_decision_log_report`'s implementation from the root-level
`decision_log_report.py` into `ai_asset_platform.reports.decision_log_report`,
with `decision_log_report.py` kept as a backward-compatibility shim and
`signal_runner.py` updated to import the package implementation directly.

Behavior (arguments, return value, exceptions, CSV output) is unchanged;
only the import location moved.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_asset_platform.reports.decision_log_report import (
    generate_decision_log_report,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


def write_decision_log(
    log_file,
    rows,
) -> None:
    log_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with log_file.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "Timestamp",
                "Ticker",
                "FinalSignal",
                "Ordered",
                "Reason",
                "AISignal",
                "AIConfidence",
                "TechnicalSignal",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_generate_decision_log_report_importable_from_package():
    """The implementation lives in the package now."""
    assert callable(generate_decision_log_report)


def test_root_decision_log_report_is_a_compatibility_shim():
    """`decision_log_report.generate_decision_log_report` still works, and
    is the *same* function object as the package implementation -- not a
    reimplementation that could drift out of sync. The same applies to the
    `LOG_FILE` / `REPORT_FILE` constants.
    """
    import decision_log_report
    from ai_asset_platform.reports.decision_log_report import (
        LOG_FILE as package_log_file,
        REPORT_FILE as package_report_file,
        generate_decision_log_report as package_generate_decision_log_report,
    )

    assert (
        decision_log_report.generate_decision_log_report
        is package_generate_decision_log_report
    )
    assert decision_log_report.LOG_FILE is package_log_file
    assert decision_log_report.REPORT_FILE is package_report_file


def test_generate_decision_log_report_creates_summary(
    tmp_path,
) -> None:
    log_file = tmp_path / "results" / "decision_log.csv"
    report_file = (
        tmp_path
        / "results"
        / "decision_log_report.csv"
    )

    write_decision_log(
        log_file,
        [
            {
                "Timestamp": "2026-07-29 07:00:00",
                "Ticker": "7203.T",
                "FinalSignal": "BUY",
                "Ordered": "YES",
                "Reason": "AI最終判定",
                "AISignal": "BUY",
                "AIConfidence": "80.0",
                "TechnicalSignal": "BUY",
            },
            {
                "Timestamp": "2026-07-29 07:01:00",
                "Ticker": "6758.T",
                "FinalSignal": "SELL",
                "Ordered": "NO",
                "Reason": "リスク管理",
                "AISignal": "SELL",
                "AIConfidence": "70.0",
                "TechnicalSignal": "SELL",
            },
            {
                "Timestamp": "2026-07-29 07:02:00",
                "Ticker": "7203.T",
                "FinalSignal": "BUY",
                "Ordered": "YES",
                "Reason": "AI最終判定",
                "AISignal": "BUY",
                "AIConfidence": "90.0",
                "TechnicalSignal": "BUY",
            },
        ],
    )

    result = generate_decision_log_report(
        log_file=log_file,
        report_file=report_file,
    )

    assert result["total_decisions"] == 3
    assert result["ordered_count"] == 2
    assert result["not_ordered_count"] == 1
    assert result["order_rate"] == 66.7
    assert result["average_ai_confidence"] == 80.0
    assert result["final_signal_counts"] == {
        "BUY": 2,
        "SELL": 1,
    }
    assert result["ticker_counts"] == {
        "7203.T": 2,
        "6758.T": 1,
    }
    assert result["reason_counts"] == {
        "AI最終判定": 2,
        "リスク管理": 1,
    }
    assert result["not_ordered_reason_counts"] == {
        "リスク管理": 1,
    }
    assert report_file.exists()

    report_rows = list(
        csv.DictReader(
            report_file.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            )
        )
    )

    assert {
        "Category": "Reason",
        "Item": "AI最終判定",
        "Value": "2",
    } in report_rows
    assert {
        "Category": "NotOrderedReason",
        "Item": "リスク管理",
        "Value": "1",
    } in report_rows


def test_generate_decision_log_report_handles_empty_log(
    tmp_path,
) -> None:
    log_file = tmp_path / "results" / "decision_log.csv"
    report_file = (
        tmp_path
        / "results"
        / "decision_log_report.csv"
    )

    write_decision_log(
        log_file,
        [],
    )

    result = generate_decision_log_report(
        log_file=log_file,
        report_file=report_file,
    )

    assert result["total_decisions"] == 0
    assert result["ordered_count"] == 0
    assert result["not_ordered_count"] == 0
    assert result["order_rate"] == 0.0
    assert result["average_ai_confidence"] == 0.0
    assert result["reason_counts"] == {}
    assert result["not_ordered_reason_counts"] == {}
    assert report_file.exists()


def test_generate_decision_log_report_rejects_missing_log(
    tmp_path,
) -> None:
    log_file = tmp_path / "missing.csv"
    report_file = tmp_path / "report.csv"

    with pytest.raises(
        FileNotFoundError,
        match="判断ログが見つかりません",
    ):
        generate_decision_log_report(
            log_file=log_file,
            report_file=report_file,
        )


def test_package_import_does_not_require_repo_root_on_sys_path(tmp_path):
    """Isolated regression, offline (no network, no venv creation, no
    dependency reinstall): import
    `ai_asset_platform.reports.decision_log_report` in a subprocess whose
    cwd is *not* the repo root and whose PYTHONPATH is set to `src/` only --
    never the repo root itself, so root-level modules like
    `decision_log_report.py` or `signal_runner.py` are never on the import
    path at all. This proves resolution *correctness* (it resolves to this
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
        src_dir / "ai_asset_platform" / "reports" / "decision_log_report.py"
    ).resolve()
    assert expected_module_path.is_file()

    env = dict(os.environ)
    # Only ever add src/ -- never the repo root -- so root-level modules
    # stay unreachable regardless of what else this interpreter already
    # has installed (e.g. an unrelated checkout's editable install, if
    # this test happens to run under a borrowed/shared venv).
    env["PYTHONPATH"] = str(src_dir)

    script = (
        "import ai_asset_platform.reports.decision_log_report as m\n"
        "import sys\n"
        "assert 'decision_log_report' not in sys.modules, ("
        "'root-level decision_log_report must not have been imported')\n"
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
        "ai_asset_platform.reports.decision_log_report resolved to a "
        f"different file than this checkout's own module: {resolved_module_path} "
        f"(expected {expected_module_path})"
    )


def test_signal_runner_does_not_import_from_root_decision_log_report():
    """Static regression: `signal_runner.py` must import the package
    implementation directly (`ai_asset_platform.reports.decision_log_report`),
    not the root-level compatibility shim (`from decision_log_report import ...`).
    """
    signal_runner_path = ROOT_DIR / "signal_runner.py"
    text = signal_runner_path.read_text(encoding="utf-8")

    assert "from decision_log_report import" not in text, (
        "signal_runner.py must not import from the root decision_log_report shim"
    )
    assert "from ai_asset_platform.reports.decision_log_report import" in text, (
        "signal_runner.py must import generate_decision_log_report/REPORT_FILE "
        "from the package implementation directly"
    )
