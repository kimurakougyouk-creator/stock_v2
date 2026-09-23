#!/usr/bin/python3
"""Run repository Python with venv packages but without site startup hooks."""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys


def _fail(message: str):
    print(f"BLOCKED: {message}", file=sys.stderr)
    raise SystemExit(2)


def _repository_root() -> Path:
    raw = os.environ.get("AI_ASSET_PLATFORM_ROOT")
    if not raw:
        _fail("AI_ASSET_PLATFORM_ROOT is missing")
    root = Path(raw).resolve()
    if not root.is_dir():
        _fail("repository root does not exist")
    return root


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
    candidates = {
        path.resolve()
        for base in (root / ".venv" / "lib", root / ".venv" / "lib64")
        if base.is_dir()
        for path in base.glob("python*/site-packages")
        if path.is_dir()
    }
    if len(candidates) != 1:
        _fail(
            "could not establish one exact checkout virtualenv site-packages "
            f"directory (found {len(candidates)})"
        )
    candidate = next(iter(candidates))
    venv_root = (root / ".venv").resolve()
    try:
        candidate.relative_to(venv_root)
    except ValueError:
        _fail("virtualenv site-packages escapes the checkout .venv")
    return candidate


def _prepare_sys_path(root: Path, site_packages: Path) -> None:
    stdlib = [
        entry
        for entry in sys.path
        if entry and Path(entry).resolve() not in {Path.cwd().resolve(), root}
    ]
    sys.path[:] = [str(root), str(root / "src"), str(site_packages), *stdlib]


def _run_script(root: Path, raw_path: str, args: list[str]) -> None:
    target = (root / raw_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        _fail("requested script escapes the checkout")
    if not target.is_file():
        _fail(f"requested script is missing: {raw_path}")
    sys.argv = [str(target), *args]
    runpy.run_path(str(target), run_name="__main__")


def main() -> int:
    if not sys.flags.isolated or not sys.flags.no_site:
        _fail("bootstrap must be launched with -I -S")
    root = _repository_root()
    os.chdir(root)
    _verify_matching_venv_interpreter(root)
    site_packages = _venv_site_packages(root)
    _prepare_sys_path(root, site_packages)

    args = sys.argv[1:]
    if not args:
        _fail("no Python target supplied")
    if args[0] == "-m":
        if len(args) < 2:
            _fail("-m requires a module name")
        module = args[1]
        sys.argv = [module, *args[2:]]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return 0
    if args[0] in {"-c", "-"}:
        _fail("inline/stdin Python execution is not allowed by this bootstrap")
    _run_script(root, args[0], args[1:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
