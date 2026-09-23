"""Manifest-bound import guard for the Live pilot's sole venv dependency.

The Live wrapper does not add the virtualenv's site-packages directory to
sys.path. After a standard-library-only preflight verifies the pinned ibapi
tree, this module installs a finder that can load only manifest-listed ibapi
source modules. Every module's exact bytes are SHA-256 checked again immediately
before those same bytes are compiled and executed.
"""
from __future__ import annotations

import hashlib
from importlib import abc, util
import io
import json
from pathlib import Path
import re
import sys
import tokenize


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_manifest(manifest_path: Path) -> dict[str, str]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("pinned ibapi manifest is unreadable") from exc
    if (
        payload.get("schema_version") != 1
        or payload.get("distribution") != "ibapi"
        or payload.get("version") != "9.81.1.post1"
    ):
        raise RuntimeError("pinned ibapi manifest identity is invalid")
    files = payload.get("package_files")
    if not isinstance(files, dict) or not files:
        raise RuntimeError("pinned ibapi manifest file map is invalid")

    normalized: dict[str, str] = {}
    for raw_name, raw_digest in files.items():
        if not isinstance(raw_name, str) or not raw_name:
            raise RuntimeError("pinned ibapi manifest contains an invalid path")
        rel = raw_name.replace("\\", "/")
        if rel.startswith("/") or ".." in Path(rel).parts or "\\" in raw_name:
            raise RuntimeError("pinned ibapi manifest contains an unsafe path")
        digest = str(raw_digest or "").lower()
        if not _SHA256_RE.fullmatch(digest):
            raise RuntimeError(f"pinned ibapi manifest hash is invalid for {rel}")
        normalized[rel] = digest
    return normalized


class _VerifiedIbapiLoader(abc.Loader):
    def __init__(
        self,
        *,
        fullname: str,
        source_path: Path,
        expected_sha256: str,
        is_package: bool,
        package_root: Path,
    ) -> None:
        self.fullname = fullname
        self.source_path = source_path
        self.expected_sha256 = expected_sha256
        self.is_package = is_package
        self.package_root = package_root

    def create_module(self, spec):
        return None

    def exec_module(self, module) -> None:
        try:
            data = self.source_path.read_bytes()
        except OSError as exc:
            raise ImportError(f"verified ibapi source is unreadable: {self.fullname}") from exc
        digest = hashlib.sha256(data).hexdigest()
        if digest != self.expected_sha256:
            raise ImportError(f"verified ibapi source hash mismatch: {self.fullname}")

        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
            source = data.decode(encoding)
        except (SyntaxError, UnicodeError) as exc:
            raise ImportError(f"verified ibapi source encoding is invalid: {self.fullname}") from exc

        module.__file__ = str(self.source_path)
        module.__loader__ = self
        if self.is_package:
            module.__package__ = self.fullname
            module.__path__ = [str(self.package_root)]
        else:
            module.__package__ = self.fullname.rpartition(".")[0]
        code = compile(source, str(self.source_path), "exec", dont_inherit=True)
        exec(code, module.__dict__)


class VerifiedIbapiFinder(abc.MetaPathFinder):
    def __init__(self, *, package_root: Path, package_files: dict[str, str]) -> None:
        self.package_root = package_root
        self.package_files = dict(package_files)

    def find_spec(self, fullname: str, path=None, target=None):
        if fullname == "ibapi":
            rel = "__init__.py"
            is_package = True
        elif fullname.startswith("ibapi."):
            suffix = fullname[len("ibapi.") :].replace(".", "/")
            package_rel = f"{suffix}/__init__.py"
            module_rel = f"{suffix}.py"
            if package_rel in self.package_files:
                rel = package_rel
                is_package = True
            elif module_rel in self.package_files:
                rel = module_rel
                is_package = False
            else:
                raise ImportError(f"ibapi import is outside pinned manifest: {fullname}")
        else:
            return None

        expected = self.package_files.get(rel)
        if expected is None:
            raise ImportError(f"ibapi import is outside pinned manifest: {fullname}")
        source_path = self.package_root / rel
        if source_path.is_symlink() or not source_path.is_file():
            raise ImportError(f"verified ibapi source path is invalid: {fullname}")
        loader = _VerifiedIbapiLoader(
            fullname=fullname,
            source_path=source_path,
            expected_sha256=expected,
            is_package=is_package,
            package_root=self.package_root,
        )
        return util.spec_from_file_location(
            fullname,
            source_path,
            loader=loader,
            submodule_search_locations=[str(self.package_root)] if is_package else None,
        )


def build_verified_ibapi_finder(
    *,
    package_dir: str | Path,
    manifest_path: str | Path,
) -> VerifiedIbapiFinder:
    package_root = Path(package_dir)
    if package_root.is_symlink() or not package_root.is_dir():
        raise RuntimeError("verified ibapi package root is invalid")
    package_files = _load_manifest(Path(manifest_path))
    return VerifiedIbapiFinder(
        package_root=package_root,
        package_files=package_files,
    )


def install_verified_ibapi_importer(
    *,
    package_dir: str | Path,
    manifest_path: str | Path,
) -> None:
    if any(name == "ibapi" or name.startswith("ibapi.") for name in sys.modules):
        raise RuntimeError("ibapi was imported before runtime attestation")
    finder = build_verified_ibapi_finder(
        package_dir=package_dir,
        manifest_path=manifest_path,
    )
    sys.meta_path.insert(0, finder)
