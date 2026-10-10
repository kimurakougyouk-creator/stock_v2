#!/usr/bin/env python3
"""Verify the ignored venv tzdata zoneinfo files before trusting them as
``PYTHONTZPATH`` on the Windows Live Pilot entrypoint.

This script intentionally uses only the Python standard library and is
executed with a trusted, Authenticode-verified system interpreter under
-I -P -S. A runtime is accepted only when the exact tzdata zoneinfo file
set and SHA-256 hashes match the immutable manifest tracked in this
repository. See ``verify_live_ibapi_runtime.py`` for the sibling check
this mirrors.
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
        _fail(f"tzdata manifest is unreadable: {exc}")
    if payload.get("schema_version") != 1:
        _fail("tzdata manifest schema is unsupported")
    if payload.get("distribution") != "tzdata":
        _fail("tzdata manifest distribution is invalid")
    files = payload.get("zoneinfo_files")
    if not isinstance(files, dict) or not files:
        _fail("tzdata manifest zoneinfo_files is invalid")
    normalized: dict[str, str] = {}
    for raw_name, raw_digest in files.items():
        if not isinstance(raw_name, str) or not raw_name:
            _fail("tzdata manifest contains an invalid file name")
        rel = raw_name.replace("\\", "/")
        parts = Path(rel).parts
        if rel.startswith("/") or ".." in parts or "\\" in raw_name:
            _fail("tzdata manifest contains an unsafe file path")
        digest = str(raw_digest or "").lower()
        if not _SHA256_RE.fullmatch(digest):
            _fail(f"tzdata manifest hash is invalid for {rel}")
        normalized[rel] = digest
    payload["zoneinfo_files"] = normalized
    return payload


def verify_runtime(*, zoneinfo_dir: Path, manifest_path: Path) -> None:
    lexical_dir = Path(os.path.abspath(zoneinfo_dir))
    try:
        resolved_dir = zoneinfo_dir.resolve(strict=True)
    except OSError as exc:
        _fail(f"tzdata zoneinfo directory cannot be resolved: {exc}")
    if resolved_dir != lexical_dir or zoneinfo_dir.is_symlink():
        _fail("tzdata zoneinfo path must not contain symlink redirection")
    if not resolved_dir.is_dir():
        _fail("tzdata zoneinfo directory is missing")

    payload = _load_manifest(manifest_path)
    expected = payload["zoneinfo_files"]
    assert isinstance(expected, dict)

    observed: dict[str, str] = {}
    for current, dirnames, filenames in os.walk(resolved_dir, followlinks=False):
        current_path = Path(current)
        for name in tuple(dirnames):
            child = current_path / name
            if child.is_symlink():
                _fail(f"symlink directory exists inside tzdata zoneinfo: {child}")
        for name in filenames:
            child = current_path / name
            if child.is_symlink():
                _fail(f"symlink file exists inside tzdata zoneinfo: {child}")
            rel_path = child.relative_to(resolved_dir)
            if "__pycache__" in rel_path.parts:
                continue
            try:
                data = child.read_bytes()
            except OSError as exc:
                _fail(f"tzdata file cannot be read: {rel_path}: {exc}")
            rel = rel_path.as_posix()
            observed[rel] = hashlib.sha256(data).hexdigest()

    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        _fail(f"tzdata zoneinfo file set mismatch; missing={missing!r} extra={extra!r}")

    for rel, digest in expected.items():
        if observed.get(rel) != digest:
            _fail(f"tzdata SHA-256 mismatch: {rel}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zoneinfo-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    verify_runtime(zoneinfo_dir=args.zoneinfo_dir, manifest_path=args.manifest)
    print("OK: pinned tzdata runtime matches immutable manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
