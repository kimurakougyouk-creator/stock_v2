#!/usr/bin/env python3
"""Verify the ignored venv ibapi package before any broker-capable import.

This script intentionally uses only the Python standard library and is executed
with a root-owned system interpreter under -I -P -S. It imports no package from
site-packages. A runtime is accepted only when the exact ibapi source-file set
and SHA-256 hashes match the immutable manifest tracked in this repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _fail(message: str) -> None:
    raise SystemExit(f"BLOCKED: {message}")


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"ibapi manifest is unreadable: {exc}")
    if payload.get("schema_version") != 1:
        _fail("ibapi manifest schema is unsupported")
    if payload.get("distribution") != "ibapi":
        _fail("ibapi manifest distribution is invalid")
    if payload.get("version") != "9.81.1.post1":
        _fail("ibapi manifest version is not the pinned version")
    files = payload.get("package_files")
    if not isinstance(files, dict) or not files:
        _fail("ibapi manifest package_files is invalid")
    normalized: dict[str, str] = {}
    for raw_name, raw_digest in files.items():
        if not isinstance(raw_name, str) or not raw_name:
            _fail("ibapi manifest contains an invalid file name")
        rel = raw_name.replace("\\", "/")
        parts = Path(rel).parts
        if rel.startswith("/") or ".." in parts or "\\" in raw_name:
            _fail("ibapi manifest contains an unsafe file path")
        digest = str(raw_digest or "").lower()
        if not _SHA256_RE.fullmatch(digest):
            _fail(f"ibapi manifest hash is invalid for {rel}")
        normalized[rel] = digest
    payload["package_files"] = normalized
    return payload


def verify_runtime(*, site_packages: Path, manifest_path: Path) -> None:
    lexical_site = Path(os.path.abspath(site_packages))
    try:
        resolved_site = site_packages.resolve(strict=True)
    except OSError as exc:
        _fail(f"venv site-packages cannot be resolved: {exc}")
    if resolved_site != lexical_site or site_packages.is_symlink():
        _fail("venv site-packages path must not contain symlink redirection")
    if not resolved_site.is_dir():
        _fail("venv site-packages directory is missing")

    package_root = resolved_site / "ibapi"
    try:
        resolved_package = package_root.resolve(strict=True)
    except OSError as exc:
        _fail(f"ibapi package cannot be resolved: {exc}")
    if package_root.is_symlink() or resolved_package != package_root:
        _fail("ibapi package path must not be a symlink")
    if not package_root.is_dir():
        _fail("ibapi package directory is missing")

    payload = _load_manifest(manifest_path)
    expected = payload["package_files"]
    assert isinstance(expected, dict)

    observed: dict[str, str] = {}
    for current, dirnames, filenames in os.walk(package_root, followlinks=False):
        current_path = Path(current)
        for name in tuple(dirnames):
            child = current_path / name
            if child.is_symlink():
                _fail(f"symlink directory exists inside ibapi: {child}")
        for name in filenames:
            child = current_path / name
            if child.is_symlink():
                _fail(f"symlink file exists inside ibapi: {child}")
            rel_path = child.relative_to(package_root)
            if "__pycache__" in rel_path.parts:
                continue
            try:
                data = child.read_bytes()
            except OSError as exc:
                _fail(f"ibapi file cannot be read: {rel_path}: {exc}")
            rel = rel_path.as_posix()
            observed[rel] = hashlib.sha256(data).hexdigest()

    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        _fail(f"ibapi file set mismatch; missing={missing!r} extra={extra!r}")

    for rel, digest in expected.items():
        if observed.get(rel) != digest:
            _fail(f"ibapi SHA-256 mismatch: {rel}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-packages", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    verify_runtime(site_packages=args.site_packages, manifest_path=args.manifest)
    print("OK: pinned ibapi runtime matches immutable manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
