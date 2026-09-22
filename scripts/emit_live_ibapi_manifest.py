#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path

EXPECTED_VERSION = "9.81.1.post1"

version = importlib.metadata.version("ibapi")
if version != EXPECTED_VERSION:
    raise SystemExit(f"unexpected ibapi version: {version!r}")

spec = importlib.util.find_spec("ibapi")
if spec is None or not spec.submodule_search_locations:
    raise SystemExit("ibapi package not found")
roots = tuple(Path(p).resolve() for p in spec.submodule_search_locations)
if len(roots) != 1:
    raise SystemExit(f"expected one ibapi package root, got {roots!r}")
root = roots[0]

files: dict[str, str] = {}
for path in sorted(root.rglob("*")):
    if "__pycache__" in path.parts:
        continue
    if path.is_symlink():
        raise SystemExit(f"unexpected symlink in ibapi package: {path}")
    if not path.is_file():
        continue
    rel = path.relative_to(root).as_posix()
    files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()

payload = {
    "schema_version": 1,
    "distribution": "ibapi",
    "version": version,
    "pypi_sdist_sha256": "49f6678bf4cced996920f32ad4b48e6897749ac30ba14a661082285f4ec09cd6",
    "package_files": files,
}
print("IBAPI_MANIFEST_BEGIN")
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
print("IBAPI_MANIFEST_END")
