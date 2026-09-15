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

P2 (offline-safety) design note / responsibility split (post CI #2046):
earlier revisions of this file ran a real `pip install -e .` inside a
disposable venv to prove the editable install resolves to the current
checkout, offline-safe via `/usr/share/python-wheels`. That path was dropped:
the exact contents of `/usr/share/python-wheels` are not guaranteed across
hosts or CI images (CI #2046 failed with `error: invalid command
'bdist_wheel'` because that directory had setuptools but not wheel there),
so a test that depends on it is not reliably offline-safe. That
verification is not this file's job: `.github/workflows/pytest.yml` already
runs the real `pip install -e .` followed by a "Verify plain-python runtime
import" step that asserts `ai_asset_platform.__file__` resolves to this
exact checkout -- and that step passed in CI #2046. This file instead only
needs to prove the *PYTHONPATH-shadowing* property (P1), which does not
require a real editable install: a single `.pth` file pointing at `src/`
reproduces the one thing that matters here -- "ai_asset_platform is
reachable via a site-packages path entry, at lower sys.path priority than an
inherited PYTHONPATH" -- without pip, setuptools, wheel, apt, or the
network.
"""
import os
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
EXPECTED_INIT_FILE = (SRC_DIR / "ai_asset_platform" / "__init__.py").resolve()

# `/tmp` is tmpfs (RAM-backed) on some dev hosts with little RAM and no swap;
# building a venv there competes with the running system for memory. Prefer a
# disk-backed temp root (`/var/tmp`) when one is available and writable, and
# fall back to the platform default (e.g. plain CI runners) otherwise.
_DISK_BACKED_TMP = (
    "/var/tmp" if os.path.isdir("/var/tmp") and os.access("/var/tmp", os.W_OK) else None
)

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


def _site_packages_dir(venv_dir: Path) -> Path:
    return venv_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"


@pytest.fixture(scope="module")
def src_path_venv():
    """A disposable, pip-free venv whose site-packages points at this checkout's src/.

    No `pip install`, no setuptools/wheel, no network, no dependency on
    `/usr/share/python-wheels`. A `.pth` file in site-packages is all that's
    needed to reproduce the sys.path property this file actually tests: that
    `ai_asset_platform` is reachable via a site-packages path entry, which
    inherited `PYTHONPATH` entries take priority over. This is *not* a claim
    that `pip install -e .` itself works offline -- that is verified by
    `.github/workflows/pytest.yml`'s own `pip install -e .` step plus its
    "Verify plain-python runtime import" step, independently of this file.
    """
    with tempfile.TemporaryDirectory(
        prefix="ai_asset_platform_pythonpath_regression_", dir=_DISK_BACKED_TMP
    ) as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=False).create(venv_dir)
        venv_python = venv_dir / "bin" / "python"
        assert venv_python.exists(), "venv creation did not produce a python executable"

        site_packages = _site_packages_dir(venv_dir)
        assert site_packages.is_dir(), f"expected venv site-packages at {site_packages}"
        (site_packages / "ai_asset_platform_checkout.pth").write_text(
            str(SRC_DIR) + "\n", encoding="utf-8"
        )

        yield venv_python


def test_wrapper_pattern_defeats_hostile_inherited_pythonpath(src_path_venv, tmp_path):
    """Dynamic proof, via the real wrapper invocation pattern, of the P1 fix.

    Simulates a parent shell/service that leaks a hostile PYTHONPATH into the
    wrapper's environment, then runs the exact sequence every operational
    wrapper now uses (`source .venv/bin/activate` -> `unset PYTHONPATH` ->
    plain `python`) and asserts resolution lands on this checkout, not the
    hostile path. Entirely offline: no pip, no network, no apt.
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
    # does shadow the src/ path entry. This proves the test setup actually
    # reproduces the Codex finding rather than trivially passing.
    vulnerable = subprocess.run(
        [str(src_path_venv), "-c", import_snippet],
        cwd=tempfile.gettempdir(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
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
    venv_dir = src_path_venv.parent.parent
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
        timeout=30,
    )
    assert fixed.returncode == 0, (
        f"wrapper-pattern invocation failed:\nstdout={fixed.stdout}\nstderr={fixed.stderr}"
    )
    resolved = Path(fixed.stdout.strip()).resolve()
    assert resolved == EXPECTED_INIT_FILE, (
        f"wrapper pattern (activate + unset PYTHONPATH) resolved to {resolved}, "
        f"expected {EXPECTED_INIT_FILE} (hostile inherited PYTHONPATH was not defeated)"
    )
