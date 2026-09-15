"""Regression test for the Codex P1 finding on PR #287 / Issue #285.

pytest's `pythonpath = src` setting (pytest.ini) makes `import ai_asset_platform`
succeed inside pytest even when the package is not actually installed anywhere.
That masked the fact that the 30 operational wrapper scripts, which invoke
`python -m ai_asset_platform...` directly (not through pytest), had no way to
resolve the package once their explicit `PYTHONPATH` export was removed.

This test proves the fix (scripts/setup.sh now runs `pip install -e .`) by
building an independent, disposable venv, installing the package the same way
setup.sh does, and confirming that a *plain* `python` subprocess with
`PYTHONPATH` unset resolves `ai_asset_platform.__file__` to this exact
checkout's `src/ai_asset_platform` -- not to pytest's path injection.
"""
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPECTED_INIT_FILE = (ROOT_DIR / "src" / "ai_asset_platform" / "__init__.py").resolve()

# `/tmp` is tmpfs (RAM-backed) on some dev hosts with little RAM and no swap;
# building a venv there competes with the running system for memory. Prefer a
# disk-backed temp root (`/var/tmp`) when one is available and writable, and
# fall back to the platform default (e.g. plain CI runners) otherwise.
_DISK_BACKED_TMP = (
    "/var/tmp" if os.path.isdir("/var/tmp") and os.access("/var/tmp", os.W_OK) else None
)


def test_editable_install_resolves_plain_python_import_to_current_checkout():
    with tempfile.TemporaryDirectory(
        prefix="ai_asset_platform_setup_regression_", dir=_DISK_BACKED_TMP
    ) as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        venv_python = venv_dir / "bin" / "python"
        assert venv_python.exists(), "venv creation did not produce a python executable"

        install = subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "-q",
                "-e",
                str(ROOT_DIR),
            ],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert install.returncode == 0, (
            f"editable install failed:\nstdout={install.stdout}\nstderr={install.stderr}"
        )

        env = dict(os.environ)
        env.pop("PYTHONPATH", None)

        check = subprocess.run(
            [
                str(venv_python),
                "-c",
                "import ai_asset_platform, os; "
                "print(os.path.realpath(ai_asset_platform.__file__))",
            ],
            cwd=tempfile.gettempdir(),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert check.returncode == 0, (
            f"plain python import failed with PYTHONPATH unset:\n"
            f"stdout={check.stdout}\nstderr={check.stderr}"
        )

        resolved = Path(check.stdout.strip()).resolve()
        assert resolved == EXPECTED_INIT_FILE, (
            f"ai_asset_platform resolved to {resolved}, expected {EXPECTED_INIT_FILE} "
            "(plain python must resolve to the current checkout, not a stale copy)"
        )
