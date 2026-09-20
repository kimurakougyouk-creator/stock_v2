"""Issue #285 follow-up: pilot Python's isolated safe-path flag (`-P`) for
`live_cash_readiness_once.sh`'s read-only runtime invocation, and prove
(hermetically, offline) that `-P` avoids picking up a same-name module
shadowing from the current working directory.

`-P` (added in Python 3.11) removes the script/cwd-derived entry from the
front of `sys.path` that a plain `python -m ...` invocation would
otherwise prepend (the empty string, i.e. cwd). This closes exactly the
class of "shadow package sitting in cwd gets imported instead of the real
one" risk this session's Issue #285 work has been hardening against,
without requiring the exact-checkout binding this test deliberately does
NOT re-verify -- `scripts/ensure_exact_checkout_runtime.sh` and CI already
cover that separately.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

REQUIRED_LINES = (
    "unset PYTHONPATH",
    "bash scripts/ensure_exact_checkout_runtime.sh",
    "python -P -m ai_asset_platform.reports.live_cash_readiness",
)


def test_live_cash_readiness_once_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", "live_cash_readiness_once.sh"],
        cwd=str(ROOT_DIR),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_live_cash_readiness_once_uses_safe_path_and_exact_checkout_verification():
    """Static regression: the wrapper must still unset PYTHONPATH, still
    verify the exact checkout before running anything, and must now
    invoke the readiness report with `-P` (not a plain `python -m`).
    """
    script = (ROOT_DIR / "live_cash_readiness_once.sh").read_text(encoding="utf-8")

    for required_line in REQUIRED_LINES:
        assert required_line in script, (
            f"live_cash_readiness_once.sh must contain: {required_line!r}"
        )

    assert "python -m ai_asset_platform.reports.live_cash_readiness" not in script, (
        "the readiness invocation must use -P, not a plain 'python -m'"
    )


def test_safe_path_does_not_import_cwd_shadow_modules(tmp_path):
    """Hermetic, offline proof that `-P` avoids a cwd-shadowed import.

    Plants two fake modules directly in a throwaway tempfile cwd:
    - dataclasses.py (shadowing a stdlib module)
    - ai_asset_platform/__init__.py (shadowing the real package)

    Each fake module, if imported, writes a sentinel file. Running
    `sys.executable -P -c ...` from that same directory, with PYTHONPATH
    removed from the subprocess environment, must import neither fake --
    proving `-P` does not let the interpreter's cwd-derived sys.path
    entry shadow real modules. This test does not assert anything about
    which *real* ai_asset_platform gets resolved (that is
    ensure_exact_checkout_runtime.sh's and CI's job) -- only that the
    fake, cwd-local one is never used.
    """
    fake_root = tmp_path
    sentinel_dataclasses = fake_root / "SENTINEL_DATACLASSES_IMPORTED"
    sentinel_package = fake_root / "SENTINEL_AI_ASSET_PLATFORM_IMPORTED"

    (fake_root / "dataclasses.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel_dataclasses)!r}).write_text('imported')\n",
        encoding="utf-8",
    )

    fake_package_dir = fake_root / "ai_asset_platform"
    fake_package_dir.mkdir()
    (fake_package_dir / "__init__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel_package)!r}).write_text('imported')\n",
        encoding="utf-8",
    )

    env = {
        key: value
        for key, value in __import__("os").environ.items()
        if key != "PYTHONPATH"
    }

    script = (
        "import dataclasses\n"
        "print(dataclasses.__file__)\n"
        "try:\n"
        "    import ai_asset_platform\n"
        "    print(ai_asset_platform.__file__)\n"
        "except ModuleNotFoundError:\n"
        "    print('ai_asset_platform: not importable (acceptable -- proves the fake was not used either)')\n"
    )

    result = subprocess.run(
        [sys.executable, "-P", "-c", script],
        cwd=str(fake_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        f"probe script failed unexpectedly:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

    assert not sentinel_dataclasses.exists(), (
        "the fake cwd-local dataclasses.py must not have been imported "
        "under -P"
    )
    assert not sentinel_package.exists(), (
        "the fake cwd-local ai_asset_platform package must not have been "
        "imported under -P"
    )

    resolved_paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for resolved_path in resolved_paths:
        if resolved_path.startswith("ai_asset_platform: not importable"):
            continue
        assert not resolved_path.startswith(str(fake_root)), (
            f"a module resolved from inside the fake cwd, not the real "
            f"installation: {resolved_path}"
        )
