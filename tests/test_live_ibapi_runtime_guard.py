from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ai_asset_platform.execution.live_ibapi_runtime_guard import (
    build_verified_ibapi_finder,
)


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    site_packages = tmp_path / "site-packages"
    package = site_packages / "ibapi"
    package.mkdir(parents=True)
    init_bytes = b"PACKAGE_VALUE = 3\n"
    client_bytes = b"VALUE = 7\n"
    (package / "__init__.py").write_bytes(init_bytes)
    (package / "client.py").write_bytes(client_bytes)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "distribution": "ibapi",
                "version": "9.81.1.post1",
                "pypi_sdist_sha256": "0" * 64,
                "package_files": {
                    "__init__.py": hashlib.sha256(init_bytes).hexdigest(),
                    "client.py": hashlib.sha256(client_bytes).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    return site_packages, package, manifest


def test_standard_library_verifier_accepts_exact_package(tmp_path: Path):
    site_packages, _, manifest = _write_fixture(tmp_path)
    verifier = Path("scripts/verify_live_ibapi_runtime.py").resolve()
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-P",
            "-S",
            str(verifier),
            "--site-packages",
            str(site_packages),
            "--manifest",
            str(manifest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "matches immutable manifest" in completed.stdout


def test_standard_library_verifier_rejects_tampered_or_extra_package_file(tmp_path: Path):
    site_packages, package, manifest = _write_fixture(tmp_path)
    verifier = Path("scripts/verify_live_ibapi_runtime.py").resolve()
    (package / "client.py").write_text("VALUE = 999\n", encoding="utf-8")
    tampered = subprocess.run(
        [
            sys.executable,
            "-I",
            "-P",
            "-S",
            str(verifier),
            "--site-packages",
            str(site_packages),
            "--manifest",
            str(manifest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert tampered.returncode != 0
    assert "SHA-256 mismatch" in (tampered.stdout + tampered.stderr)

    site_packages, package, manifest = _write_fixture(tmp_path / "extra")
    (package / "payload.py").write_text("raise RuntimeError('no')\n", encoding="utf-8")
    extra = subprocess.run(
        [
            sys.executable,
            "-I",
            "-P",
            "-S",
            str(verifier),
            "--site-packages",
            str(site_packages),
            "--manifest",
            str(manifest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert extra.returncode != 0
    assert "file set mismatch" in (extra.stdout + extra.stderr)


def test_verified_loader_hashes_the_exact_bytes_it_executes(tmp_path: Path):
    _, package, manifest = _write_fixture(tmp_path)
    finder = build_verified_ibapi_finder(
        package_dir=package,
        manifest_path=manifest,
    )
    spec = finder.find_spec("ibapi.client")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.VALUE == 7

    (package / "client.py").write_text("VALUE = 999\n", encoding="utf-8")
    spec = finder.find_spec("ibapi.client")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(ImportError, match="hash mismatch"):
        spec.loader.exec_module(module)


def test_finder_rejects_ibapi_module_not_listed_in_manifest(tmp_path: Path):
    _, package, manifest = _write_fixture(tmp_path)
    (package / "payload.py").write_text("VALUE = 1\n", encoding="utf-8")
    finder = build_verified_ibapi_finder(
        package_dir=package,
        manifest_path=manifest,
    )
    with pytest.raises(ImportError, match="outside pinned manifest"):
        finder.find_spec("ibapi.payload")


def test_live_wrapper_never_adds_whole_venv_site_packages_to_sys_path():
    source = Path("live_pilot_operational_once.sh").read_text(encoding="utf-8")
    assert "verify_live_ibapi_runtime.py" in source
    assert "install_verified_ibapi_importer" in source
    assert "sys.path.insert(0, site_packages)" not in source
    assert 'sys.path.insert(0, repo_root + "/src")' in source
