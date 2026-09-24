#!/usr/bin/python3
"""Run repository Python from an attested Git snapshot with verified venv bytes."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tarfile
import tempfile


def _fail(message: str):
    print(f"BLOCKED: {message}", file=sys.stderr)
    raise SystemExit(2)


_SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BOOTSTRAP_SOURCE_SHA_ENV = "AI_ASSET_BOOTSTRAP_STRATEGY_SOURCE_SHA"
_RUNTIME_DEPENDENCY_SHA_ENV = "AI_ASSET_RUNTIME_DEPENDENCY_SHA"


def _repository_root() -> Path:
    raw = os.environ.get("AI_ASSET_PLATFORM_ROOT")
    if not raw:
        _fail("AI_ASSET_PLATFORM_ROOT is missing")
    root = Path(raw).resolve()
    if not root.is_dir():
        _fail("repository root does not exist")
    return root


def _clean_env(root: Path) -> dict[str, str]:
    return {
        "HOME": os.environ.get("HOME", ""),
        "USER": os.environ.get("USER", ""),
        "LOGNAME": os.environ.get("LOGNAME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "AI_ASSET_PLATFORM_ROOT": str(root),
    }


def _attest_clean_source_before_repository_imports(root: Path) -> str:
    try:
        completed = subprocess.run(
            [
                "/bin/bash",
                "--noprofile",
                "--norc",
                str(root / "scripts" / "verify_strategy_source_clean.sh"),
            ],
            cwd=root,
            env=_clean_env(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        _fail("pre-import strategy source attestation failed")

    prefix = "STRATEGY_SOURCE_SHA="
    matches = [
        line[len(prefix):].strip().lower()
        for line in completed.stdout.splitlines()
        if line.startswith(prefix)
    ]
    if len(matches) != 1 or not _SOURCE_SHA_RE.fullmatch(matches[0]):
        _fail("pre-import strategy source SHA is unavailable")
    source_sha = matches[0]
    os.environ[_BOOTSTRAP_SOURCE_SHA_ENV] = source_sha
    return source_sha


def _verify_matching_venv_interpreter(root: Path) -> None:
    venv_python = root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        _fail("virtualenv Python is missing")
    try:
        matches = venv_python.samefile(Path(sys.executable))
    except OSError:
        _fail("virtualenv Python identity could not be verified")
    if not matches:
        _fail(
            "virtualenv Python does not match the trusted bootstrap interpreter; "
            "recreate .venv with /usr/bin/python3"
        )


def _venv_site_packages(root: Path) -> Path:
    expected_name = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = {
        path.resolve()
        for base in (root / ".venv" / "lib", root / ".venv" / "lib64")
        if base.is_dir()
        for path in base.glob("python*/site-packages")
        if path.is_dir() and path.parent.name == expected_name
    }
    if len(candidates) != 1:
        _fail(
            "could not establish one interpreter-matching checkout virtualenv "
            f"site-packages directory (found {len(candidates)})"
        )
    candidate = next(iter(candidates))
    venv_root = (root / ".venv").resolve()
    try:
        candidate.relative_to(venv_root)
    except ValueError:
        _fail("virtualenv site-packages escapes the checkout .venv")

    cache_tag = str(getattr(sys.implementation, "cache_tag", "") or "")
    for native in candidate.rglob("*.so"):
        name = native.name
        if ".cpython-" in name and cache_tag and f".{cache_tag}-" not in name:
            _fail(
                "native extension ABI does not match running interpreter: "
                f"{native.name}"
            )
    return candidate


def _verify_site_packages_records(site_packages: Path) -> str:
    """Verify wheel RECORD hashes and bind the exact dependency byte set."""
    if site_packages.is_symlink():
        _fail("site-packages must not be a symlink")

    for cache in site_packages.rglob("__pycache__"):
        if cache.is_dir():
            _fail(
                "executable dependency cache is present: "
                f"{cache.relative_to(site_packages)}"
            )
    for suffix in ("*.pyc", "*.pyo"):
        found = next(site_packages.rglob(suffix), None)
        if found is not None:
            _fail(
                "executable dependency bytecode is present: "
                f"{found.relative_to(site_packages)}"
            )

    records = sorted(site_packages.glob("*.dist-info/RECORD"))
    if not records:
        _fail("site-packages has no distribution RECORD metadata")

    root = site_packages.resolve()
    verified: dict[str, str] = {}
    record_digests: dict[str, str] = {}

    for record in records:
        dist_rel = record.relative_to(site_packages).as_posix()
        record_digests[dist_rel] = hashlib.sha256(record.read_bytes()).hexdigest()
        try:
            rows = list(csv.reader(record.read_text(encoding="utf-8").splitlines()))
        except (OSError, UnicodeError, csv.Error):
            _fail(f"dependency RECORD is unreadable: {dist_rel}")

        for row in rows:
            if len(row) < 3 or not row[0]:
                _fail(f"dependency RECORD row is malformed: {dist_rel}")
            raw_rel, raw_hash, _raw_size = row[:3]
            lexical = site_packages / raw_rel
            resolved = lexical.resolve()
            try:
                rel = resolved.relative_to(root).as_posix()
            except ValueError:
                continue
            if rel.endswith(".dist-info/RECORD"):
                continue
            if lexical.is_symlink():
                _fail(f"dependency symlink is not allowed: {raw_rel}")
            if not resolved.exists():
                _fail(f"dependency file listed in RECORD is missing: {rel}")
            if not resolved.is_file():
                continue
            if not raw_hash:
                _fail(f"dependency file lacks a RECORD hash: {rel}")
            try:
                algorithm, encoded = raw_hash.split("=", 1)
            except ValueError:
                _fail(f"dependency RECORD hash is malformed: {rel}")
            if algorithm.lower() != "sha256":
                _fail(f"dependency RECORD hash algorithm is not sha256: {rel}")
            try:
                expected = base64.urlsafe_b64decode(
                    encoded + "=" * (-len(encoded) % 4)
                ).hex()
            except (ValueError, TypeError):
                _fail(f"dependency RECORD hash encoding is invalid: {rel}")
            observed = hashlib.sha256(resolved.read_bytes()).hexdigest()
            if observed != expected:
                _fail(f"dependency SHA-256 mismatch: {rel}")
            previous = verified.get(rel)
            if previous is not None and previous != observed:
                _fail(f"dependency file has conflicting RECORD ownership: {rel}")
            verified[rel] = observed

    for current, dirnames, filenames in os.walk(site_packages, followlinks=False):
        current_path = Path(current)
        for dirname in tuple(dirnames):
            child = current_path / dirname
            if child.is_symlink():
                _fail(
                    "dependency directory symlink is not allowed: "
                    f"{child.relative_to(site_packages)}"
                )
        for filename in filenames:
            child = current_path / filename
            if child.is_symlink():
                _fail(
                    "dependency file symlink is not allowed: "
                    f"{child.relative_to(site_packages)}"
                )
            rel = child.relative_to(site_packages).as_posix()
            if rel.endswith(".dist-info/RECORD"):
                continue
            if rel.endswith((".pyc", ".pyo")) or "/__pycache__/" in f"/{rel}":
                _fail(f"executable dependency cache is present: {rel}")
            if rel not in verified:
                _fail(f"dependency file is not covered by RECORD hashes: {rel}")

    digest = hashlib.sha256()
    for rel, file_hash in sorted(verified.items()):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    for rel, file_hash in sorted(record_digests.items()):
        digest.update(b"RECORD\0")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    dependency_sha = digest.hexdigest()
    if not _SHA256_RE.fullmatch(dependency_sha):
        _fail("runtime dependency digest is unavailable")
    os.environ[_RUNTIME_DEPENDENCY_SHA_ENV] = dependency_sha
    return dependency_sha


def _verify_pinned_ibapi(root: Path, site_packages: Path) -> None:
    try:
        subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                "-P",
                "-S",
                str(root / "scripts" / "verify_live_ibapi_runtime.py"),
                "--site-packages",
                str(site_packages),
                "--manifest",
                str(root / "scripts" / "live_ibapi_manifest.json"),
            ],
            cwd=root,
            env=_clean_env(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        _fail("pinned ibapi runtime verification failed")


def _snapshot_repository(
    root: Path, source_sha: str
) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Extract exact committed bytes so imports cannot race worktree mutations."""
    try:
        completed = subprocess.run(
            [
                "/usr/bin/git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "archive",
                "--format=tar",
                source_sha,
            ],
            cwd=root,
            env=_clean_env(root),
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        _fail("could not create exact source snapshot from attested Git HEAD")

    holder = tempfile.TemporaryDirectory(prefix="stock_v2_attested_")
    snapshot = Path(holder.name).resolve()
    try:
        with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                target = (snapshot / member.name).resolve()
                try:
                    target.relative_to(snapshot)
                except ValueError:
                    _fail("Git archive contains an unsafe path")
                if member.issym() or member.islnk() or member.isdev():
                    _fail(
                        "Git archive contains an unsupported link/device: "
                        f"{member.name}"
                    )
            archive.extractall(snapshot, filter="data")
    except (tarfile.TarError, OSError):
        holder.cleanup()
        _fail("could not materialize exact source snapshot")

    for path in sorted(snapshot.rglob("*"), reverse=True):
        try:
            if path.is_file():
                path.chmod(0o444)
            elif path.is_dir():
                path.chmod(0o555)
        except OSError:
            holder.cleanup()
            _fail("could not make source snapshot read-only")
    snapshot.chmod(0o555)
    os.environ["AI_ASSET_CODE_SNAPSHOT_ROOT"] = str(snapshot)
    return holder, snapshot


def _prepare_sys_path(snapshot_root: Path, site_packages: Path) -> None:
    stdlib = [
        entry
        for entry in sys.path
        if entry
        and Path(entry).resolve()
        not in {Path.cwd().resolve(), snapshot_root.resolve()}
    ]
    sys.path[:] = [
        str(snapshot_root),
        str(snapshot_root / "src"),
        str(site_packages),
        *stdlib,
    ]


def _run_script(snapshot_root: Path, raw_path: str, args: list[str]) -> None:
    target = (snapshot_root / raw_path).resolve()
    try:
        target.relative_to(snapshot_root)
    except ValueError:
        _fail("requested script escapes the attested snapshot")
    if not target.is_file():
        _fail(f"requested script is missing from attested snapshot: {raw_path}")
    sys.argv = [str(target), *args]
    runpy.run_path(str(target), run_name="__main__")


def main() -> int:
    if not sys.flags.isolated or not sys.flags.no_site:
        _fail("bootstrap must be launched with -I -S")

    root = _repository_root()
    os.chdir(root)
    _verify_matching_venv_interpreter(root)
    source_sha = _attest_clean_source_before_repository_imports(root)
    site_packages = _venv_site_packages(root)
    _verify_site_packages_records(site_packages)

    args = sys.argv[1:]
    if not args:
        _fail("no Python target supplied")

    broker_runtime = (
        len(args) >= 2
        and args[0] == "-m"
        and args[1] == "ai_asset_platform.execution.ibkr_verified_paper_runtime"
    )
    if broker_runtime:
        _verify_pinned_ibapi(root, site_packages)

    snapshot_holder, snapshot_root = _snapshot_repository(root, source_sha)
    try:
        _prepare_sys_path(snapshot_root, site_packages)
        if args[0] == "-m":
            if len(args) < 2:
                _fail("-m requires a module name")
            module = args[1]
            module_args = list(args[2:])
            if module == "pytest":
                module_args = [
                    str(snapshot_root / arg)
                    if arg.startswith("tests/") and not arg.startswith("-")
                    else arg
                    for arg in module_args
                ]
            sys.argv = [module, *module_args]
            runpy.run_module(module, run_name="__main__", alter_sys=True)
            return 0
        if args[0] in {"-c", "-"}:
            _fail("inline/stdin Python execution is not allowed by this bootstrap")
        _run_script(snapshot_root, args[0], args[1:])
        return 0
    finally:
        snapshot_holder.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
