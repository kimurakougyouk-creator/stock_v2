from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[1]
WRAPPERS = {
    "ibkr_verified_paper_runtime_once.sh":
        "scripts/ibkr_verified_paper_runtime_once_sanitized.sh",
    "ibkr_strategy_profitability_evidence_once.sh":
        "scripts/ibkr_strategy_profitability_evidence_once_sanitized.sh",
    "strategy_promotion_policy_once.sh":
        "scripts/strategy_promotion_policy_once_sanitized.sh",
}


@pytest.mark.parametrize(("wrapper_name", "body_name"), WRAPPERS.items())
def test_wrapper_enters_clean_shell_before_bash_body(
    tmp_path: Path, wrapper_name: str, body_name: str
):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    wrapper = root / wrapper_name
    shutil.copy2(ROOT / wrapper_name, wrapper)
    wrapper.chmod(0o755)

    body = root / body_name
    body.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "test -z \"\${BASH_ENV:-}\"\n"
        "test -z \"\${ENV:-}\"\n"
        "test \"$PATH\" = /usr/local/bin:/usr/bin:/bin\n"
        "printf clean > body-ran.marker\n",
        encoding="utf-8",
    )
    body.chmod(0o755)

    hook_marker = root / "hook-ran.marker"
    hook = tmp_path / "hostile-bash-env.sh"
    hook.write_text(
        f"printf hostile > {hook_marker!s}\n"
        "git() { return 99; }\n"
        "export -f git\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env.update(
        {
            "AI_ASSET_PLATFORM_ROOT": str(root),
            "BASH_ENV": str(hook),
            "ENV": str(hook),
            "PATH": str(tmp_path / "hostile-bin"),
            "BASH_FUNC_git%%": "() { return 99; }",
        }
    )
    completed = subprocess.run(
        [str(wrapper)],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert (root / "body-ran.marker").read_text(encoding="utf-8") == "clean"
    assert not hook_marker.exists()


def test_isolated_bootstrap_does_not_process_venv_startup_hooks(tmp_path: Path):
    root = tmp_path / "repo"
    src = root / "src"
    src.mkdir(parents=True)
    site_packages = (
        root
        / ".venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    site_packages.mkdir(parents=True)

    pth_marker = tmp_path / "pth.marker"
    site_marker = tmp_path / "site.marker"
    user_marker = tmp_path / "user.marker"
    target_marker = tmp_path / "target.marker"

    (site_packages / "hostile.pth").write_text(
        f"import pathlib; pathlib.Path({str(pth_marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    (site_packages / "sitecustomize.py").write_text(
        f"from pathlib import Path; Path({str(site_marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    (site_packages / "usercustomize.py").write_text(
        f"from pathlib import Path; Path({str(user_marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    (site_packages / "targetmod.py").write_text(
        f"from pathlib import Path; Path({str(target_marker)!r}).write_text('ok')\n",
        encoding="utf-8",
    )

    env = {
        "AI_ASSET_PLATFORM_ROOT": str(root),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            str(ROOT / "scripts" / "run_isolated_venv_python.py"),
            "-m",
            "targetmod",
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert target_marker.read_text(encoding="utf-8") == "ok"
    assert not pth_marker.exists()
    assert not site_marker.exists()
    assert not user_marker.exists()


def test_operational_isolation_files_are_inside_source_attestation():
    shell_gate = (ROOT / "scripts" / "verify_strategy_source_clean.sh").read_text(
        encoding="utf-8"
    )
    python_gate = (
        ROOT
        / "src"
        / "ai_asset_platform"
        / "reports"
        / "strategy_source_attestation.py"
    ).read_text(encoding="utf-8")
    for path in (
        "scripts/run_isolated_venv_python.py",
        "scripts/ibkr_verified_paper_runtime_once_sanitized.sh",
        "scripts/ibkr_strategy_profitability_evidence_once_sanitized.sh",
        "scripts/strategy_promotion_policy_once_sanitized.sh",
    ):
        assert path in shell_gate
        assert path in python_gate
    assert "/usr/bin/git rev-parse" in shell_gate
    assert "/usr/bin/git status" in shell_gate
    assert "/usr/bin/git ls-files" in shell_gate
    assert "/usr/bin/awk" in shell_gate


@pytest.mark.parametrize("wrapper_name", WRAPPERS)
def test_operational_entrypoints_are_minimal_posix_trampolines(wrapper_name: str):
    source = (ROOT / wrapper_name).read_text(encoding="utf-8")
    assert source.startswith("#!/bin/sh\n")
    assert "/usr/bin/env -i" in source
    assert "/bin/bash --noprofile --norc" in source
