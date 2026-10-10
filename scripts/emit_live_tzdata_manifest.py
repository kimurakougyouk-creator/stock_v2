#!/usr/bin/env python3
"""Emit an immutable file-hash manifest for the pinned ``tzdata`` package.

Windows has no OS-provided IANA time zone database (unlike POSIX systems,
where ``zoneinfo`` falls back to ``/usr/share/zoneinfo``), so the Live
Pilot Windows entrypoint points ``PYTHONTZPATH`` directly at this package's
``zoneinfo/`` directory of raw TZif files. Those files are untrusted
venv/site-packages content from the trusted interpreter's point of view,
so they go through the same manifest-pinning discipline as ``ibapi``
before being trusted (see ``emit_live_ibapi_manifest.py``).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path


def build_manifest() -> dict[str, object]:
    version = importlib.metadata.version("tzdata")
    spec = importlib.util.find_spec("tzdata")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("tzdata package not found")
    roots = tuple(Path(p).resolve() for p in spec.submodule_search_locations)
    if len(roots) != 1:
        raise SystemExit(f"expected one tzdata package root, got {roots!r}")
    package_root = roots[0]
    zoneinfo_root = package_root / "zoneinfo"
    if not zoneinfo_root.is_dir():
        raise SystemExit(f"tzdata zoneinfo directory not found under {package_root}")

    files: dict[str, str] = {}
    for path in sorted(zoneinfo_root.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise SystemExit(f"unexpected symlink in tzdata zoneinfo: {path}")
        if not path.is_file():
            continue
        rel = path.relative_to(zoneinfo_root).as_posix()
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "schema_version": 1,
        "distribution": "tzdata",
        "version": version,
        "zoneinfo_files": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    manifest = build_manifest()
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.check is not None:
        existing = args.check.read_text(encoding="utf-8")
        if existing != rendered:
            raise SystemExit(
                "live_tzdata_manifest.json is stale; regenerate with --out"
            )
        print("OK: pinned tzdata runtime manifest matches installed package")
        return 0
    if args.out is not None:
        args.out.write_text(rendered, encoding="utf-8")
        print(f"wrote {args.out}")
        return 0
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
