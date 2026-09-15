"""Regression tests for the Codex findings on PR #287 / Issue #285.

Original finding (P1, first review): pytest's `pythonpath = src` setting
(pytest.ini) makes `import ai_asset_platform` succeed inside pytest even when
the package is not actually installed anywhere. That masked the fact that the
IBKR operational wrapper scripts, which invoke `python -m ai_asset_platform...`
directly (not through pytest), had no way to resolve the package once their
explicit `PYTHONPATH` export was removed. Fixed by `scripts/setup.sh` /
`.github/workflows/pytest.yml` running `pip install -e .`.

Follow-up finding (P1, second review): venv activation (`source
.venv/bin/activate`) does not clear a `PYTHONPATH` inherited from the parent
shell/service environment, and inherited `PYTHONPATH` entries resolve before
the venv's own site-packages (where the editable install lives). A stale or
attacker-controlled `PYTHONPATH` could therefore still shadow the editable
install in every operational wrapper. Fixed by adding `unset PYTHONPATH`
immediately after `source .venv/bin/activate` in every wrapper script, before
any `ai_asset_platform` invocation. This file verifies (a) statically that
every such wrapper carries the fix in the right place, and (b) dynamically
that the fix mechanism actually defeats a hostile inherited `PYTHONPATH`.

Follow-up finding (P2): the editable install used PEP 517 build isolation,
which builds an isolated environment for the build backend
(`setuptools>=68`, per pyproject.toml) and fetches it from PyPI even though
the runtime dependency install already used `--no-deps`. That breaks on
offline hosts. Fixed by bootstrapping setuptools from the local
Debian/Ubuntu wheel cache (`/usr/share/python-wheels`, shipped by the system
`python3-pip` package specifically for ensurepip-style offline bootstrapping)
and passing `--no-build-isolation`, so the editable install never touches the
network.
"""
import os
import re
import subprocess
import tempfile
import venv
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
EXPECTED_INIT_FILE = (ROOT_DIR / "src" / "ai_asset_platform" / "__init__.py").resolve()

# `/tmp` is tmpfs (RAM-backed) on some dev hosts with little RAM and no swap;
# building a venv there competes with the running system for memory. Prefer a
# disk-backed temp root (`/var/tmp`) when one is available and writable, and
# fall back to the platform default (e.g. plain CI runners) otherwise.
_DISK_BACKED_TMP = (
    "/var/tmp" if os.path.isdir("/var/tmp") and os.access("/var/tmp", os.W_OK) else None
)

# Debian/Ubuntu ship pip's and setuptools' bootstrap wheels here so ensurepip
# (and venv creation) never needs the network. We reuse it to make the
# editable install offline-safe too. GitHub Actions ubuntu-* runners are
# Debian-based and carry the same path.
_OFFLINE_WHEEL_DIR = Path("/usr/share/python-wheels")

_WRAPPER_INVOCATION_RE = re.compile(r"python3?\s+(\S+\s+)*-m\s+ai_asset_platform\b")
_ACTIVATE_RE = re.compile(r"^\s*source \.venv/bin/activate\s*$")
_UNSET_PYTHONPATH_RE = re.compile(r"^\s*unset PYTHONPATH\s*$")


def _discover_operational_wrappers():
    """Every *.sh script (repo root + scripts/) that invokes ai_asset_platform."""
    candidates = sorted(ROOT_DIR.glob("*.sh")) + sorted((ROOT_DIR / "scripts").glob("*.sh"))
    wrappers = [
        path
        for path in candidates
        if _WRAPPER_INVOCATION_RE.search(path.read_text(encoding="utf-8"))
    ]
    return wrappers


def _bootstrap_setuptools_offline(venv_python: Path) -> None:
    if not _OFFLINE_WHEEL_DIR.is_dir():
        pytest.skip(
            f"offline setuptools wheel cache not found at {_OFFLINE_WHEEL_DIR}; "
            "cannot verify the offline-safe editable install path on this host"
        )
    result = subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(_OFFLINE_WHEEL_DIR),
            "-q",
            "setuptools",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"offline setuptools bootstrap failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


@pytest.fixture(scope="module")
def editable_venv():
    """A disposable venv with ai_asset_platform editable-installed, offline-safe."""
    with tempfile.TemporaryDirectory(
        prefix="ai_asset_platform_setup_regression_", dir=_DISK_BACKED_TMP
    ) as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        venv_python = venv_dir / "bin" / "python"
        assert venv_python.exists(), "venv creation did not produce a python executable"

        _bootstrap_setuptools_offline(venv_python)

        install = subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
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
            f"offline-safe editable install failed:\nstdout={install.stdout}\nstderr={install.stderr}"
        )

        yield venv_python


def test_all_operational_wrappers_clear_inherited_pythonpath_before_first_use():
    """Static proof that every wrapper neutralizes inherited PYTHONPATH.

    Every wrapper must `unset PYTHONPATH` after `source .venv/bin/activate`
    and before its first `ai_asset_platform` invocation, so an inherited
    PYTHONPATH from the parent shell/service can never shadow the editable
    install.
    """
    wrappers = _discover_operational_wrappers()
    assert len(wrappers) >= 30, (
        f"expected at least 30 ai_asset_platform operational wrappers, found {len(wrappers)}: "
        f"{[w.name for w in wrappers]}"
    )

    failures = []
    for path in wrappers:
        lines = path.read_text(encoding="utf-8").splitlines()
        activate_idx = next((i for i, l in enumerate(lines) if _ACTIVATE_RE.match(l)), None)
        first_use_idx = next(
            (i for i, l in enumerate(lines) if _WRAPPER_INVOCATION_RE.search(l)), None
        )
        if activate_idx is None or first_use_idx is None:
            failures.append(f"{path.name}: could not locate activate/first-use lines")
            continue
        if activate_idx >= first_use_idx:
            failures.append(
                f"{path.name}: venv activation (line {activate_idx + 1}) does not precede "
                f"first ai_asset_platform invocation (line {first_use_idx + 1})"
            )
            continue
        unset_idx = next(
            (
                i
                for i in range(activate_idx + 1, first_use_idx)
                if _UNSET_PYTHONPATH_RE.match(lines[i])
            ),
            None,
        )
        if unset_idx is None:
            failures.append(
                f"{path.name}: no 'unset PYTHONPATH' between venv activation "
                f"(line {activate_idx + 1}) and first ai_asset_platform invocation "
                f"(line {first_use_idx + 1})"
            )

    assert not failures, "wrappers vulnerable to inherited PYTHONPATH shadowing:\n" + "\n".join(
        failures
    )


def test_editable_install_resolves_plain_python_import_to_current_checkout(editable_venv):
    """Offline-safe editable install resolves to this checkout with PYTHONPATH unset."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    check = subprocess.run(
        [
            str(editable_venv),
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


def test_wrapper_pattern_defeats_hostile_inherited_pythonpath(editable_venv, tmp_path):
    """Dynamic proof, via the real wrapper invocation pattern, of the P1 fix.

    Simulates a parent shell/service that leaks a hostile PYTHONPATH into the
    wrapper's environment, then runs the exact sequence every operational
    wrapper now uses (`source .venv/bin/activate` -> `unset PYTHONPATH` ->
    plain `python`) and asserts resolution lands on this checkout, not the
    hostile path.
    """
    hostile_dir = tmp_path / "hostile_pythonpath"
    hostile_pkg = hostile_dir / "ai_asset_platform"
    hostile_pkg.mkdir(parents=True)
    hostile_init = hostile_pkg / "__init__.py"
    hostile_init.write_text("HOSTILE = True\n", encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(hostile_dir)

    import_snippet = (
        "import ai_asset_platform, os; "
        "print(os.path.realpath(ai_asset_platform.__file__))"
    )

    # Sanity check: without the fix, the hostile inherited PYTHONPATH really
    # does shadow the editable install. This proves the test setup actually
    # reproduces the Codex finding rather than trivially passing.
    vulnerable = subprocess.run(
        [str(editable_venv), "-c", import_snippet],
        cwd=tempfile.gettempdir(),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert vulnerable.returncode == 0, (
        f"hostile-PYTHONPATH sanity import failed:\n"
        f"stdout={vulnerable.stdout}\nstderr={vulnerable.stderr}"
    )
    assert Path(vulnerable.stdout.strip()).resolve() == hostile_init.resolve(), (
        "test setup did not reproduce the hostile-PYTHONPATH-shadowing precondition; "
        f"resolved to {vulnerable.stdout.strip()!r} instead of the hostile package"
    )

    # The actual fix: `source .venv/bin/activate` followed by
    # `unset PYTHONPATH`, exactly as every operational wrapper now does
    # before its first ai_asset_platform invocation.
    venv_dir = editable_venv.parent.parent
    activate_script = venv_dir / "bin" / "activate"
    fixed = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{activate_script}" && unset PYTHONPATH && python -c "{import_snippet}"',
        ],
        cwd=tempfile.gettempdir(),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert fixed.returncode == 0, (
        f"wrapper-pattern invocation failed:\nstdout={fixed.stdout}\nstderr={fixed.stderr}"
    )
    resolved = Path(fixed.stdout.strip()).resolve()
    assert resolved == EXPECTED_INIT_FILE, (
        f"wrapper pattern (activate + unset PYTHONPATH) resolved to {resolved}, "
        f"expected {EXPECTED_INIT_FILE} (hostile inherited PYTHONPATH was not defeated)"
    )
