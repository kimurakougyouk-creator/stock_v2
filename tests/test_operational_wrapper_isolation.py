from __future__ import annotations

import base64
import hashlib
import json
import importlib
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
        "test -z \"${BASH_ENV:-}\"\n"
        "test -z \"${ENV:-}\"\n"
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


def test_isolated_bootstrap_rejects_unverified_venv_startup_hooks(tmp_path: Path):
    root = tmp_path / "repo"
    src = root / "src"
    src.mkdir(parents=True)
    system_version = subprocess.check_output(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        text=True,
    ).strip()
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    gate = scripts / "verify_strategy_source_clean.sh"
    gate.write_text(
        "#!/bin/bash\n"
        "printf 'STRATEGY_SOURCE_SHA=%040d\\n' 0 | tr 0 a\n",
        encoding="utf-8",
    )
    gate.chmod(0o755)

    venv_bin = root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to("/usr/bin/python3")
    site_packages = (
        root / ".venv" / "lib" / f"python{system_version}" / "site-packages"
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
    dist = site_packages / "fixture-1.0.dist-info"
    dist.mkdir()
    (dist / "RECORD").write_text("", encoding="utf-8")

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
    assert completed.returncode == 2
    assert not target_marker.exists()
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
    assert "safe_git rev-parse" in shell_gate
    assert "safe_git status" in shell_gate
    assert "safe_git ls-files" in shell_gate
    assert "core.fsmonitor=false" in shell_gate
    assert "core.hooksPath=/dev/null" in shell_gate
    assert "/usr/bin/awk" in shell_gate


@pytest.mark.parametrize("wrapper_name", WRAPPERS)
def test_operational_entrypoints_are_minimal_posix_trampolines(wrapper_name: str):
    source = (ROOT / wrapper_name).read_text(encoding="utf-8")
    assert source.startswith("#!/bin/sh\n")
    assert "/usr/bin/env -i" in source
    assert "/bin/bash --noprofile --norc" in source


@pytest.mark.parametrize(("wrapper_name", "body_name"), WRAPPERS.items())
def test_explicit_bash_invocation_is_rejected(
    tmp_path: Path, wrapper_name: str, body_name: str
):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    wrapper = root / wrapper_name
    shutil.copy2(ROOT / wrapper_name, wrapper)
    wrapper.chmod(0o755)
    body = root / body_name
    body.write_text(
        "#!/bin/bash\nprintf should-not-run > body-ran.marker\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["/bin/bash", str(wrapper)],
        cwd=root,
        env={**os.environ, "AI_ASSET_PLATFORM_ROOT": str(root)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "directly" in completed.stderr
    assert not (root / "body-ran.marker").exists()


def test_isolated_bootstrap_rejects_mismatched_venv_interpreter(tmp_path: Path):
    root = tmp_path / "repo"
    fake_python = root / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)
    (root / ".venv" / "lib" / "python999" / "site-packages").mkdir(parents=True)

    completed = subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            str(ROOT / "scripts" / "run_isolated_venv_python.py"),
            "-m",
            "does_not_matter",
        ],
        cwd=root,
        env={
            "AI_ASSET_PLATFORM_ROOT": str(root),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "does not match the trusted bootstrap interpreter" in completed.stderr


def test_isolated_bootstrap_blocks_before_repository_module_when_attestation_fails(
    tmp_path: Path,
):
    root = tmp_path / "repo"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    gate_marker = tmp_path / "gate.marker"
    target_marker = tmp_path / "target.marker"

    gate = scripts / "verify_strategy_source_clean.sh"
    gate.write_text(
        "#!/bin/bash\n"
        f"printf checked > {gate_marker!s}\n"
        "exit 2\n",
        encoding="utf-8",
    )
    gate.chmod(0o755)

    system_version = subprocess.check_output(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        text=True,
    ).strip()
    venv_bin = root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to("/usr/bin/python3")
    site_packages = (
        root / ".venv" / "lib" / f"python{system_version}" / "site-packages"
    )
    site_packages.mkdir(parents=True)
    (site_packages / "targetmod.py").write_text(
        f"from pathlib import Path; Path({str(target_marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )

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
        env={
            "AI_ASSET_PLATFORM_ROOT": str(root),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert gate_marker.exists()
    assert not target_marker.exists()
    assert "pre-import strategy source attestation failed" in completed.stderr


def test_verified_paper_wrapper_never_self_updates_checkout():
    source = (
        ROOT / "scripts" / "ibkr_verified_paper_runtime_once_sanitized.sh"
    ).read_text(encoding="utf-8")
    for forbidden in ("git pull", "git fetch", "git switch", "ext::"):
        assert forbidden not in source


def test_venv_site_packages_must_match_running_python_minor(tmp_path: Path):
    root = tmp_path / "repo"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").symlink_to("/usr/bin/python3")
    (root / ".venv" / "lib" / "python9.99" / "site-packages").mkdir(parents=True)

    completed = subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            str(ROOT / "scripts" / "run_isolated_venv_python.py"),
            "-m",
            "does_not_matter",
        ],
        cwd=root,
        env={
            "AI_ASSET_PLATFORM_ROOT": str(root),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "interpreter-matching" in completed.stderr


def test_verified_dependency_snapshot_isolated_from_original_mutation(tmp_path: Path):
    from scripts import run_isolated_venv_python as isolated_bootstrap

    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    module_name = "frozen_dependency_fixture"
    trusted_bytes = b'VALUE = "trusted"\n'
    module_path = site_packages / f"{module_name}.py"
    module_path.write_bytes(trusted_bytes)

    encoded = base64.urlsafe_b64encode(
        hashlib.sha256(trusted_bytes).digest()
    ).decode("ascii").rstrip("=")
    dist_info = site_packages / "fixture-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "RECORD").write_text(
        f"{module_name}.py,sha256={encoded},{len(trusted_bytes)}\n"
        "fixture-1.0.dist-info/RECORD,,\n",
        encoding="utf-8",
    )

    holder, snapshot, dependency_sha, verified_sources, verified_hashes = (
        isolated_bootstrap._snapshot_verified_site_packages(site_packages)
    )
    frozen_path = snapshot / f"{module_name}.py"
    original_sys_path = list(sys.path)
    original_path_hooks = list(sys.path_hooks)
    original_importer_cache = dict(sys.path_importer_cache)
    try:
        # Same-UID processes can undo chmod and rewrite temporary files. The
        # importer must still execute the exact bytes captured during verification.
        frozen_path.chmod(0o644)
        frozen_path.write_text('VALUE = "hostile"\n', encoding="utf-8")
        assert frozen_path.read_text(encoding="utf-8") == 'VALUE = "hostile"\n'

        isolated_bootstrap._install_verified_dependency_importer(
            snapshot,
            verified_sources,
            verified_hashes,
        )
        sys.modules.pop(module_name, None)
        sys.path[:] = [str(snapshot), *original_sys_path]
        sys.path_importer_cache.pop(str(snapshot), None)

        imported = importlib.import_module(module_name)
        assert imported.VALUE == "trusted"
        assert len(dependency_sha) == 64
        assert os.environ["AI_ASSET_RUNTIME_DEPENDENCY_SHA"] == dependency_sha
    finally:
        sys.modules.pop(module_name, None)
        sys.path[:] = original_sys_path
        sys.path_hooks[:] = original_path_hooks
        sys.path_importer_cache.clear()
        sys.path_importer_cache.update(original_importer_cache)
        holder.cleanup()



def test_repository_importer_uses_verified_archive_bytes_after_same_uid_rewrite(
    tmp_path: Path,
):
    from scripts import run_isolated_venv_python as isolated_bootstrap

    snapshot = tmp_path / "repo"
    snapshot.mkdir()
    module_name = "verified_repository_fixture"
    module_path = snapshot / f"{module_name}.py"
    module_path.write_text('VALUE = "hostile"\n', encoding="utf-8")
    verified_sources = {f"{module_name}.py": b'VALUE = "trusted"\n'}

    original_sys_path = list(sys.path)
    original_path_hooks = list(sys.path_hooks)
    original_importer_cache = dict(sys.path_importer_cache)
    try:
        isolated_bootstrap._install_verified_repository_importer(
            snapshot,
            verified_sources,
        )
        sys.modules.pop(module_name, None)
        sys.path[:] = [str(snapshot), *original_sys_path]
        sys.path_importer_cache.pop(str(snapshot), None)
        imported = importlib.import_module(module_name)
        assert imported.VALUE == "trusted"
    finally:
        sys.modules.pop(module_name, None)
        sys.path[:] = original_sys_path
        sys.path_hooks[:] = original_path_hooks
        sys.path_importer_cache.clear()
        sys.path_importer_cache.update(original_importer_cache)


def test_repository_entrypoint_executes_verified_archive_bytes(tmp_path: Path):
    from scripts import run_isolated_venv_python as isolated_bootstrap

    snapshot = tmp_path / "repo"
    snapshot.mkdir()
    marker = tmp_path / "entrypoint.marker"
    entry = snapshot / "entry.py"
    entry.write_text(
        f"from pathlib import Path; Path({str(marker)!r}).write_text('hostile')\n",
        encoding="utf-8",
    )
    trusted = (
        f"from pathlib import Path; Path({str(marker)!r}).write_text('trusted')\n"
    ).encode("utf-8")

    old_argv = list(sys.argv)
    try:
        isolated_bootstrap._run_script(
            snapshot,
            {"entry.py": trusted},
            "entry.py",
            [],
        )
    finally:
        sys.argv[:] = old_argv

    assert marker.read_text(encoding="utf-8") == "trusted"


def test_native_payload_is_loaded_from_sealed_verified_bytes(tmp_path: Path):
    from scripts import run_isolated_venv_python as isolated_bootstrap

    spec = importlib.util.find_spec("_testcapi")
    if spec is None or not spec.origin or not any(
        spec.origin.endswith(suffix)
        for suffix in importlib.machinery.EXTENSION_SUFFIXES
    ):
        pytest.skip("dynamic _testcapi extension is unavailable")

    trusted = Path(spec.origin).read_bytes()
    candidate = tmp_path / Path(spec.origin).name
    candidate.write_bytes(trusted)
    root = tmp_path
    rel = candidate.relative_to(root).as_posix()
    verified_hashes = {rel: hashlib.sha256(trusted).hexdigest()}

    sealed_spec = isolated_bootstrap._sealed_verified_native_spec(
        "_testcapi",
        candidate,
        root,
        verified_hashes,
        is_package=False,
    )
    assert sealed_spec is not None
    candidate.write_bytes(b"hostile replacement")

    previous = sys.modules.pop("_testcapi", None)
    try:
        module = importlib.util.module_from_spec(sealed_spec)
        sealed_spec.loader.exec_module(module)
        assert module.__name__ == "_testcapi"
        assert str(module.__file__).startswith("/proc/self/fd/")
        assert candidate.read_bytes() == b"hostile replacement"
    finally:
        sys.modules.pop("_testcapi", None)
        if previous is not None:
            sys.modules["_testcapi"] = previous



def test_sealed_native_loader_preserves_bundled_origin_dependencies(tmp_path: Path):
    from scripts import run_isolated_venv_python as isolated_bootstrap

    import ctypes

    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("C compiler is unavailable")

    root = tmp_path / "site-packages"
    package = root / "fixture"
    bundled = root / "fixture.libs"
    package.mkdir(parents=True)
    bundled.mkdir(parents=True)

    dep_source = tmp_path / "dep.c"
    main_source = tmp_path / "main.c"
    dep_source.write_text(
        "int stock_v2_fixture_value(void) { return 41; }\n",
        encoding="utf-8",
    )
    main_source.write_text(
        "extern int stock_v2_fixture_value(void);\n"
        "int stock_v2_fixture_main(void) { return stock_v2_fixture_value() + 1; }\n",
        encoding="utf-8",
    )

    dep = bundled / "libstock_v2_fixture_dep.so"
    main = package / "libstock_v2_fixture_main.so"
    subprocess.run(
        [
            compiler,
            "-shared",
            "-fPIC",
            str(dep_source),
            "-Wl,-soname,libstock_v2_fixture_dep.so",
            "-o",
            str(dep),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            compiler,
            "-shared",
            "-fPIC",
            str(main_source),
            "-L",
            str(bundled),
            "-lstock_v2_fixture_dep",
            "-Wl,-rpath,$ORIGIN/../fixture.libs",
            "-o",
            str(main),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    verified_hashes = {
        dep.relative_to(root).as_posix(): hashlib.sha256(dep.read_bytes()).hexdigest(),
        main.relative_to(root).as_posix(): hashlib.sha256(main.read_bytes()).hexdigest(),
    }

    isolated_bootstrap._preload_verified_bundled_libraries(
        main,
        root,
        verified_hashes,
    )
    sealed_main = isolated_bootstrap._sealed_verified_dependency_path(
        main,
        root,
        verified_hashes,
    )
    assert sealed_main is not None

    dep.write_bytes(b"hostile dependency replacement")
    main.write_bytes(b"hostile extension replacement")

    loaded = ctypes.CDLL(sealed_main)
    loaded.stock_v2_fixture_main.restype = ctypes.c_int
    assert loaded.stock_v2_fixture_main() == 42


def test_ibapi_verifier_uses_retained_repository_bytes(tmp_path: Path):
    from scripts import run_isolated_venv_python as isolated_bootstrap

    root = tmp_path / "snapshot"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()

    (scripts / "verify_live_ibapi_runtime.py").write_text(
        "raise SystemExit('hostile worktree verifier executed')\n",
        encoding="utf-8",
    )
    (scripts / "live_ibapi_manifest.json").write_text(
        '{"trusted": false}\n',
        encoding="utf-8",
    )

    trusted_payload = b"VALUE = 1\n"
    digest = hashlib.sha256(trusted_payload).hexdigest()
    verifier_source = (
        b"import argparse, json\n"
        b"from pathlib import Path\n"
        b"p = argparse.ArgumentParser()\n"
        b"p.add_argument('--site-packages', required=True)\n"
        b"p.add_argument('--manifest', required=True)\n"
        b"a = p.parse_args()\n"
        b"payload = json.loads(Path(a.manifest).read_text(encoding='utf-8'))\n"
        b"assert payload['distribution'] == 'ibapi'\n"
    )
    manifest_payload = json.dumps(
        {
            "schema_version": 1,
            "distribution": "ibapi",
            "version": "9.81.1.post1",
            "package_files": {"__init__.py": digest},
        },
        sort_keys=True,
    ).encode("utf-8")
    verified_repository_sources = {
        "scripts/verify_live_ibapi_runtime.py": verifier_source,
        "scripts/live_ibapi_manifest.json": manifest_payload,
    }
    verified_python_sources = {"ibapi/__init__.py": trusted_payload}

    isolated_bootstrap._verify_pinned_ibapi(
        root,
        site_packages,
        verified_repository_sources,
        verified_python_sources,
    )


def test_ibapi_verifier_rejects_retained_payload_swap(tmp_path: Path, monkeypatch):
    from scripts import run_isolated_venv_python as isolated_bootstrap

    root = tmp_path / "snapshot"
    root.mkdir()
    site_packages = tmp_path / "site-packages"
    package = site_packages / "ibapi"
    package.mkdir(parents=True)

    trusted_payload = b"VALUE = 1\n"
    hostile_retained_payload = b"VALUE = 'hostile retained bytes'\n"
    (package / "__init__.py").write_bytes(trusted_payload)

    digest = hashlib.sha256(trusted_payload).hexdigest()
    manifest_payload = json.dumps(
        {
            "schema_version": 1,
            "distribution": "ibapi",
            "version": "9.81.1.post1",
            "package_files": {"__init__.py": digest},
        },
        sort_keys=True,
    ).encode("utf-8")
    verified_repository_sources = {
        "scripts/verify_live_ibapi_runtime.py": b"raise AssertionError('subprocess must not run')\n",
        "scripts/live_ibapi_manifest.json": manifest_payload,
    }
    verified_python_sources = {
        "ibapi/__init__.py": hostile_retained_payload,
    }

    called = False

    def _unexpected_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("verifier subprocess must not run after retained-byte mismatch")

    monkeypatch.setattr(isolated_bootstrap.subprocess, "run", _unexpected_run)

    with pytest.raises(SystemExit, match="retained ibapi payload SHA-256 mismatch"):
        isolated_bootstrap._verify_pinned_ibapi(
            root,
            site_packages,
            verified_repository_sources,
            verified_python_sources,
        )

    assert called is False
