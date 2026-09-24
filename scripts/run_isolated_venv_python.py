#!/usr/bin/python3
"""Run repository Python from an attested Git snapshot with verified venv bytes."""
from __future__ import annotations

import base64
import csv
import ctypes
import fcntl
import hashlib
import io
import json
import importlib.abc
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import re
import runpy
import shutil
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
_SEALED_NATIVE_FDS: list[int] = []
_SEALED_NATIVE_HANDLES: list[ctypes.CDLL] = []
_SEALED_NATIVE_PATHS: dict[tuple[str, str, str], str] = {}
_PRELOADED_NATIVE_RELS: set[tuple[str, str, str]] = set()


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


def _verify_site_packages_records(
    site_packages: Path,
) -> tuple[str, dict[str, bytes], dict[str, str]]:
    """Verify wheel RECORD hashes and retain exact verified import identities."""
    if site_packages.is_symlink():
        _fail("site-packages must not be a symlink")

    # Existing __pycache__ files are ignored at import time by rebinding
    # sys.pycache_prefix to an empty trusted directory before any dependency
    # import. Standalone/legacy bytecode outside __pycache__ remains forbidden
    # because PathFinder can load it directly without source.
    for suffix in ("*.pyc", "*.pyo"):
        for found in site_packages.rglob(suffix):
            rel_parts = found.relative_to(site_packages).parts
            if "__pycache__" not in rel_parts:
                _fail(
                    "standalone dependency bytecode is present: "
                    f"{found.relative_to(site_packages)}"
                )

    records = sorted(site_packages.glob("*.dist-info/RECORD"))
    if not records:
        _fail("site-packages has no distribution RECORD metadata")

    root = site_packages.resolve()
    verified: dict[str, str] = {}
    verified_python_sources: dict[str, bytes] = {}
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
            payload = resolved.read_bytes()
            observed = hashlib.sha256(payload).hexdigest()
            if observed != expected:
                _fail(f"dependency SHA-256 mismatch: {rel}")
            previous = verified.get(rel)
            if previous is not None and previous != observed:
                _fail(f"dependency file has conflicting RECORD ownership: {rel}")
            verified[rel] = observed
            if rel.endswith(".py"):
                verified_python_sources[rel] = payload

    for current, dirnames, filenames in os.walk(site_packages, followlinks=False):
        current_path = Path(current)
        for dirname in tuple(dirnames):
            child = current_path / dirname
            if child.is_symlink():
                _fail(
                    "dependency directory symlink is not allowed: "
                    f"{child.relative_to(site_packages)}"
                )
        # Never trust or enumerate installed caches. They are not importable
        # in this process because sys.pycache_prefix is redirected below.
        dirnames[:] = [name for name in dirnames if name != "__pycache__"]
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
            if rel.endswith((".pyc", ".pyo")):
                _fail(f"standalone dependency bytecode is present: {rel}")
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
    return dependency_sha, verified_python_sources, dict(verified)


def _snapshot_verified_site_packages(
    site_packages: Path,
) -> tuple[
    tempfile.TemporaryDirectory[str],
    Path,
    str,
    dict[str, bytes],
    dict[str, str],
]:
    """Copy dependencies and retain verified import identities for later imports."""
    holder = tempfile.TemporaryDirectory(prefix="stock_v2_dependencies_")
    snapshot = (Path(holder.name) / "site-packages").resolve()
    try:
        shutil.copytree(
            site_packages,
            snapshot,
            symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    except (OSError, shutil.Error):
        holder.cleanup()
        _fail("could not snapshot checkout virtualenv dependencies")

    try:
        dependency_sha, verified_python_sources, verified_hashes = (
            _verify_site_packages_records(snapshot)
        )
    except SystemExit:
        holder.cleanup()
        raise

    for path in sorted(snapshot.rglob("*"), reverse=True):
        if path.is_symlink():
            holder.cleanup()
            _fail(
                "dependency snapshot contains a symlink: "
                f"{path.relative_to(snapshot)}"
            )
        try:
            if path.is_file():
                path.chmod(0o444)
            elif path.is_dir():
                path.chmod(0o555)
        except OSError:
            holder.cleanup()
            _fail("could not make dependency snapshot read-only")
    try:
        snapshot.chmod(0o555)
    except OSError:
        holder.cleanup()
        _fail("could not make dependency snapshot read-only")

    os.environ[_RUNTIME_DEPENDENCY_SHA_ENV] = dependency_sha
    return (
        holder,
        snapshot,
        dependency_sha,
        verified_python_sources,
        verified_hashes,
    )


class _VerifiedDependencySourceLoader(importlib.abc.SourceLoader):
    """Load Python code from the exact bytes captured during RECORD verification."""

    def __init__(self, fullname: str, filename: Path, source: bytes):
        self._fullname = fullname
        self._filename = filename
        self._source = source

    def get_filename(self, fullname: str) -> str:
        if fullname != self._fullname:
            raise ImportError(fullname)
        return str(self._filename)

    def get_data(self, path: str) -> bytes:
        if Path(path).resolve() != self._filename.resolve():
            raise OSError(path)
        return self._source

    def set_data(self, path: str, data: bytes, *_args, **_kwargs) -> None:
        return None


class _VerifiedDependencyPathFinder(importlib.abc.PathEntryFinder):
    """Resolve dependency Python modules from verified in-memory source bytes."""

    def __init__(
        self,
        path_entry: str,
        snapshot_root: Path,
        verified_python_sources: dict[str, bytes],
        verified_hashes: dict[str, str],
    ):
        self._entry = Path(path_entry).resolve()
        self._root = snapshot_root.resolve()
        self._sources = verified_python_sources
        self._hashes = verified_hashes

    def _verified_loader(
        self, fullname: str, candidate: Path
    ) -> _VerifiedDependencySourceLoader | None:
        try:
            rel = candidate.resolve().relative_to(self._root).as_posix()
        except ValueError:
            return None
        source = self._sources.get(rel)
        if source is None:
            return None
        return _VerifiedDependencySourceLoader(fullname, candidate.resolve(), source)

    def find_spec(self, fullname: str, target=None):
        leaf = fullname.rsplit(".", 1)[-1]
        package_init = self._entry / leaf / "__init__.py"
        loader = self._verified_loader(fullname, package_init)
        if loader is not None:
            spec = importlib.util.spec_from_loader(
                fullname,
                loader,
                origin=str(package_init),
                is_package=True,
            )
            if spec is None:
                return None
            spec.submodule_search_locations = [str(package_init.parent.resolve())]
            return spec

        module_file = self._entry / f"{leaf}.py"
        loader = self._verified_loader(fullname, module_file)
        if loader is not None:
            return importlib.util.spec_from_loader(
                fullname,
                loader,
                origin=str(module_file),
                is_package=False,
            )

        for suffix in importlib.machinery.EXTENSION_SUFFIXES:
            package_native = self._entry / leaf / f"__init__{suffix}"
            spec = _sealed_verified_native_spec(
                fullname,
                package_native,
                self._root,
                self._hashes,
                is_package=True,
                package_dir=package_native.parent,
            )
            if spec is not None:
                return spec

            module_native = self._entry / f"{leaf}{suffix}"
            spec = _sealed_verified_native_spec(
                fullname,
                module_native,
                self._root,
                self._hashes,
                is_package=False,
            )
            if spec is not None:
                return spec

        return None


def _read_exact_verified_file(
    path: Path,
    root: Path,
    verified_hashes: dict[str, str],
) -> bytes | None:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return None
    expected = verified_hashes.get(rel)
    if expected is None:
        return None

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        _fail(f"verified dependency disappeared before import: {rel}")
    except OSError:
        _fail(f"verified dependency could not be opened safely: {rel}")
    try:
        with os.fdopen(fd, "rb", closefd=True) as handle:
            payload = handle.read()
    except OSError:
        _fail(f"verified dependency could not be read safely: {rel}")

    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected:
        _fail(f"verified dependency changed before import: {rel}")
    return payload


def _seal_verified_native_payload(payload: bytes, label: str) -> str:
    if not hasattr(os, "memfd_create"):
        _fail("sealed native dependency loading requires Linux memfd support")
    required = ("F_ADD_SEALS", "F_GET_SEALS", "F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")
    if any(not hasattr(fcntl, name) for name in required):
        _fail("sealed native dependency loading requires Linux file seals")

    flags = getattr(os, "MFD_CLOEXEC", 0) | getattr(os, "MFD_ALLOW_SEALING", 0)
    fd = -1
    try:
        fd = os.memfd_create(label, flags)
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError("short memfd write")
            offset += written
        os.lseek(fd, 0, os.SEEK_SET)
        seals = (
            fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_SEAL
        )
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
        if (fcntl.fcntl(fd, fcntl.F_GET_SEALS) & seals) != seals:
            raise OSError("native memfd seals were not applied")
        os.set_inheritable(fd, False)
    except OSError:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        _fail("could not create sealed native dependency payload")

    _SEALED_NATIVE_FDS.append(fd)
    return f"/proc/self/fd/{fd}"


def _sealed_verified_dependency_path(
    path: Path,
    root: Path,
    verified_hashes: dict[str, str],
) -> str | None:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return None
    expected = verified_hashes.get(rel)
    if expected is None:
        return None
    key = (str(root), rel, expected)
    cached = _SEALED_NATIVE_PATHS.get(key)
    if cached is not None:
        return cached
    payload = _read_exact_verified_file(path, root, verified_hashes)
    if payload is None:
        return None
    sealed_path = _seal_verified_native_payload(payload, path.name)
    _SEALED_NATIVE_PATHS[key] = sealed_path
    return sealed_path


def _is_bundled_native_library(rel: str, package_root: str) -> bool:
    prefixes = (
        f"{package_root}.libs/",
        f"{package_root}/.libs/",
        f"{package_root}/libs/",
    )
    if not rel.startswith(prefixes):
        return False
    name = Path(rel).name.lower()
    return ".so" in name or name.endswith((".dylib", ".dll"))


def _preload_verified_bundled_libraries(
    candidate: Path,
    root: Path,
    verified_hashes: dict[str, str],
) -> None:
    """Preload RECORD-bound wheel libraries so sealed extensions keep $ORIGIN semantics."""
    try:
        candidate_rel = candidate.relative_to(root).as_posix()
    except ValueError:
        return
    package_root = candidate_rel.split("/", 1)[0]
    bundled = [
        rel
        for rel in sorted(verified_hashes)
        if _is_bundled_native_library(rel, package_root)
    ]
    if not bundled:
        return

    pending: list[tuple[tuple[str, str, str], str]] = []
    for rel in bundled:
        expected = verified_hashes[rel]
        key = (str(root), rel, expected)
        if key in _PRELOADED_NATIVE_RELS:
            continue
        sealed_path = _sealed_verified_dependency_path(
            root / rel,
            root,
            verified_hashes,
        )
        if sealed_path is not None:
            pending.append((key, sealed_path))

    if not pending:
        return

    mode = getattr(os, "RTLD_NOW", 2) | getattr(os, "RTLD_GLOBAL", 0x100)
    while pending:
        progress = False
        retry: list[tuple[tuple[str, str, str], str]] = []
        for key, sealed_path in pending:
            try:
                handle = ctypes.CDLL(sealed_path, mode=mode)
            except OSError:
                retry.append((key, sealed_path))
                continue
            _SEALED_NATIVE_HANDLES.append(handle)
            _PRELOADED_NATIVE_RELS.add(key)
            progress = True
        if not retry or not progress:
            break
        pending = retry


def _sealed_verified_native_spec(
    fullname: str,
    candidate: Path,
    root: Path,
    verified_hashes: dict[str, str],
    *,
    is_package: bool,
    package_dir: Path | None = None,
):
    _preload_verified_bundled_libraries(candidate, root, verified_hashes)
    sealed_path = _sealed_verified_dependency_path(candidate, root, verified_hashes)
    if sealed_path is None:
        return None
    loader = importlib.machinery.ExtensionFileLoader(fullname, sealed_path)
    spec = importlib.util.spec_from_loader(
        fullname,
        loader,
        origin=sealed_path,
        is_package=is_package,
    )
    if spec is None:
        _fail(f"could not create sealed native import spec: {fullname}")
    if is_package:
        spec.submodule_search_locations = [str((package_dir or candidate.parent).resolve())]
    return spec


def _install_verified_dependency_importer(
    snapshot_root: Path,
    verified_python_sources: dict[str, bytes],
    verified_hashes: dict[str, str],
) -> None:
    """Bind dependency imports to exact bytes validated during verification."""
    root = snapshot_root.resolve()

    def path_hook(path_entry: str):
        entry = Path(path_entry).resolve()
        try:
            entry.relative_to(root)
        except ValueError as exc:
            raise ImportError(path_entry) from exc
        return _VerifiedDependencyPathFinder(
            str(entry),
            root,
            verified_python_sources,
            verified_hashes,
        )

    sys.path_hooks.insert(0, path_hook)
    for cached in tuple(sys.path_importer_cache):
        try:
            Path(cached).resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        sys.path_importer_cache.pop(cached, None)


def _verify_pinned_ibapi(
    snapshot_root: Path,
    site_packages: Path,
    verified_repository_sources: dict[str, bytes],
    verified_python_sources: dict[str, bytes],
) -> None:
    verifier_rel = "scripts/verify_live_ibapi_runtime.py"
    manifest_rel = "scripts/live_ibapi_manifest.json"
    verifier_source = verified_repository_sources.get(verifier_rel)
    manifest_payload = verified_repository_sources.get(manifest_rel)
    if verifier_source is None or manifest_payload is None:
        _fail("pinned ibapi verifier/manifest is missing from attested Git archive")

    try:
        manifest = json.loads(manifest_payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        _fail("attested ibapi manifest is unreadable")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("distribution") != "ibapi"
        or manifest.get("version") != "9.81.1.post1"
    ):
        _fail("attested ibapi manifest metadata is invalid")
    expected_files = manifest.get("package_files")
    if not isinstance(expected_files, dict) or not expected_files:
        _fail("attested ibapi manifest package_files is invalid")

    retained_ibapi: dict[str, bytes] = {}
    prefix = "ibapi/"
    for rel, payload in verified_python_sources.items():
        if rel.startswith(prefix):
            retained_ibapi[rel[len(prefix):]] = payload

    if set(retained_ibapi) != set(expected_files):
        _fail("retained ibapi payload set does not match attested manifest")
    for rel, payload in retained_ibapi.items():
        expected_digest = expected_files.get(rel)
        if not isinstance(expected_digest, str) or not _SHA256_RE.fullmatch(
            expected_digest.lower()
        ):
            _fail(f"attested ibapi manifest hash is invalid for {rel}")
        if hashlib.sha256(payload).hexdigest() != expected_digest.lower():
            _fail(f"retained ibapi payload SHA-256 mismatch: {rel}")

    manifest_path = _seal_verified_native_payload(
        manifest_payload,
        "stock_v2_live_ibapi_manifest",
    )
    try:
        manifest_fd = int(manifest_path.rsplit("/", 1)[-1])
    except (ValueError, IndexError):
        _fail("sealed ibapi manifest descriptor is unavailable")

    bootstrap = (
        "import sys\n"
        + f"source = {verifier_source!r}\n"
        + f"sys.argv = [{verifier_rel!r}, '--site-packages', {str(site_packages)!r}, "
        + f"'--manifest', {manifest_path!r}]\n"
        + "namespace = {"
        + f"'__name__': '__main__', '__file__': {verifier_rel!r}, "
        + "'__package__': None, '__spec__': None, '__cached__': None, "
        + "'__builtins__': __builtins__}\n"
        + f"exec(compile(source, {verifier_rel!r}, 'exec'), namespace, namespace)\n"
    )
    try:
        subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                "-P",
                "-S",
                "-c",
                bootstrap,
            ],
            cwd=snapshot_root,
            env=_clean_env(snapshot_root),
            pass_fds=(manifest_fd,),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        _fail("pinned ibapi runtime verification failed")


def _snapshot_repository(
    root: Path, source_sha: str
) -> tuple[tempfile.TemporaryDirectory[str], Path, dict[str, bytes]]:
    """Extract committed bytes and retain exact Python bytes for execution."""
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
    verified_repository_sources: dict[str, bytes] = {}
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
                if member.isfile() and (
                    member.name.endswith(".py")
                    or member.name == "scripts/live_ibapi_manifest.json"
                ):
                    stream = archive.extractfile(member)
                    if stream is None:
                        _fail(f"could not read archived repository source: {member.name}")
                    verified_repository_sources[member.name] = stream.read()
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
    return holder, snapshot, verified_repository_sources


def _install_verified_repository_importer(
    snapshot_root: Path,
    verified_repository_sources: dict[str, bytes],
) -> None:
    """Bind repository Python imports to bytes read from the exact Git archive."""
    root = snapshot_root.resolve()

    def path_hook(path_entry: str):
        entry = Path(path_entry).resolve()
        try:
            entry.relative_to(root)
        except ValueError as exc:
            raise ImportError(path_entry) from exc
        return _VerifiedDependencyPathFinder(
            str(entry),
            root,
            verified_repository_sources,
            {},
        )

    sys.path_hooks.insert(0, path_hook)
    for cached in tuple(sys.path_importer_cache):
        try:
            Path(cached).resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        sys.path_importer_cache.pop(cached, None)


def _prepare_sys_path(
    snapshot_root: Path,
    site_packages: Path,
    verified_python_sources: dict[str, bytes],
    verified_hashes: dict[str, str],
    verified_repository_sources: dict[str, bytes],
) -> None:
    stdlib = [
        entry
        for entry in sys.path
        if entry
        and Path(entry).resolve()
        not in {Path.cwd().resolve(), snapshot_root.resolve()}
    ]
    _install_verified_dependency_importer(
        site_packages,
        verified_python_sources,
        verified_hashes,
    )
    _install_verified_repository_importer(
        snapshot_root,
        verified_repository_sources,
    )
    sys.path[:] = [
        str(snapshot_root),
        str(snapshot_root / "src"),
        str(site_packages),
        *stdlib,
    ]


def _run_script(
    snapshot_root: Path,
    verified_repository_sources: dict[str, bytes],
    raw_path: str,
    args: list[str],
) -> None:
    target = (snapshot_root / raw_path).resolve()
    try:
        rel = target.relative_to(snapshot_root).as_posix()
    except ValueError:
        _fail("requested script escapes the attested snapshot")
    source = verified_repository_sources.get(rel)
    if source is None:
        _fail(f"requested script is not verified archive Python: {raw_path}")
    sys.argv = [str(target), *args]
    namespace = {
        "__name__": "__main__",
        "__file__": str(target),
        "__package__": None,
        "__spec__": None,
        "__cached__": None,
        "__builtins__": __builtins__,
    }
    exec(compile(source, str(target), "exec"), namespace, namespace)


def main() -> int:
    if not sys.flags.isolated or not sys.flags.no_site:
        _fail("bootstrap must be launched with -I -S")

    root = _repository_root()
    os.chdir(root)
    _verify_matching_venv_interpreter(root)
    # Interpreter/ABI compatibility can be checked without importing any
    # repository or venv code, so fail on a stale venv before source work.
    site_packages = _venv_site_packages(root)
    source_sha = _attest_clean_source_before_repository_imports(root)
    (
        dependency_holder,
        dependency_snapshot,
        _dependency_sha,
        verified_python_sources,
        verified_hashes,
    ) = _snapshot_verified_site_packages(site_packages)

    # Force importlib to ignore mutable site-packages/__pycache__ contents.
    # The temporary cache root starts empty and no trusted import may fall back
    # to package-local bytecode caches.
    pycache_holder = tempfile.TemporaryDirectory(prefix="stock_v2_pycache_")
    sys.pycache_prefix = pycache_holder.name
    sys.dont_write_bytecode = True

    args = sys.argv[1:]
    if not args:
        _fail("no Python target supplied")

    broker_runtime = (
        len(args) >= 2
        and args[0] == "-m"
        and args[1] == "ai_asset_platform.execution.ibkr_verified_paper_runtime"
    )
    raw_require_pinned_ibapi = os.environ.get("AI_ASSET_REQUIRE_PINNED_IBAPI", "0")
    if raw_require_pinned_ibapi not in {"0", "1"}:
        _fail("AI_ASSET_REQUIRE_PINNED_IBAPI must be exactly 0 or 1")
    require_pinned_ibapi = broker_runtime or raw_require_pinned_ibapi == "1"

    (
        snapshot_holder,
        snapshot_root,
        verified_repository_sources,
    ) = _snapshot_repository(root, source_sha)
    try:
        if require_pinned_ibapi:
            _verify_pinned_ibapi(
                snapshot_root,
                dependency_snapshot,
                verified_repository_sources,
                verified_python_sources,
            )
        _prepare_sys_path(
            snapshot_root,
            dependency_snapshot,
            verified_python_sources,
            verified_hashes,
            verified_repository_sources,
        )
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
        _run_script(
            snapshot_root,
            verified_repository_sources,
            args[0],
            args[1:],
        )
        return 0
    finally:
        snapshot_holder.cleanup()
        pycache_holder.cleanup()
        dependency_holder.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
