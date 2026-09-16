#!/usr/bin/env python3
"""Fail-closed check: does `ai_asset_platform` resolve to *this* checkout?

Must be run with cwd at the repository root (both callers already `cd`
there). Exits non-zero on any import-origin mismatch -- including when a
stale or un-migrated install resolves `ai_asset_platform` to some other
checkout. Never trusts pytest's `pythonpath = src` injection (pytest.ini);
this only checks what a plain `python` process would see, which is what the
operational wrappers and the read-only autopilot service actually run.

Shared by:
- scripts/setup.sh (fresh setup)
- install_ibkr_readonly_autopilot.sh (existing-install migration, before any
  service restart)

Import-context note (Codex PR #287 P1, PRRT_kwDOTZGJWc6i2VXi): every real
caller invokes `python -m ai_asset_platform...`, where Python prepends
`sys.path[0] = cwd` (the repo root). This script instead runs as `python
scripts/verify_exact_checkout_import.py`, where Python prepends
`sys.path[0] = <this script's own directory>` (`scripts/`) -- a different
sys.path than the real invocations it verifies. An untracked (so `git
switch`/`git pull`/`git diff` checks never see it) `ai_asset_platform/`
directory sitting directly at the repo root would be invisible to this
check (`scripts/` doesn't contain it) while still shadowing the editable
install for every real `-m ai_asset_platform...` call (repo root does
contain it, and repo root is `sys.path[0]` there). `sys.path[0]` is
corrected to match the real invocation context below before resolving
anything, so this check sees exactly what those callers would.

Execute-before-verify note (Codex PR #287 P1, PRRT_kwDOTZGJWc6i3eu6): an
earlier version of this check did `import ai_asset_platform` and only
*then* looked at `ai_asset_platform.__file__` to decide safety. That
executes the target package's code (whatever it is -- the real one, or a
root-level shadow) before judging whether it is safe to run at all. A
shadow package's own `__init__.py` can trivially rebind its module-level
`__file__` while running (`__file__ = "<forged path>"`), so by the time
this script reads `ai_asset_platform.__file__`, an attacker-controlled
shadow can have already executed *and* forged the path this check trusts.
Fixed by using `importlib.util.find_spec("ai_asset_platform")` to resolve
where the package *would* be loaded from, purely by searching `sys.path`
-- the standard import finders (`PathFinder`) locate a package by walking
directories and never execute `__init__.py` to do it -- and judging safety
entirely from that spec, before importing anything. Only after the spec's
origin (and, since this project's package is a regular package with
submodules, its search locations) are confirmed to be exactly this
checkout's `src/ai_asset_platform/` does this script import the package at
all, as an optional plain sanity check that it imports cleanly -- by then
it is judged safe, so running it is no longer the risk the fix removes.
"""
import importlib.util
import os
import sys


def main() -> int:
    # Match sys.path[0] to what `python -m ai_asset_platform...` actually
    # uses (cwd), not this script's own directory (`scripts/`) -- see the
    # module docstring. Must happen before resolving anything below.
    sys.path[0] = os.getcwd()

    expected_dir = os.path.realpath(os.path.join(os.getcwd(), "src", "ai_asset_platform"))

    # `find_spec` only searches sys.path for a matching module/package and
    # reports where it *would* load from -- it does not execute anything,
    # so a shadow package's code (and any forged __file__ it might set once
    # running) never runs before this safety judgment.
    try:
        spec = importlib.util.find_spec("ai_asset_platform")
    except Exception as exc:  # noqa: BLE001 - fail-closed diagnostic, any resolution failure is fatal
        print(
            f"FATAL: ai_asset_platform の import spec を解決できません: {exc}",
            file=sys.stderr,
        )
        return 1

    if spec is None:
        print("FATAL: ai_asset_platform が見つかりません（import spec が存在しません）。", file=sys.stderr)
        return 1

    if spec.origin is None:
        print(
            "FATAL: ai_asset_platform の import origin を確定できません "
            f"(namespace package など想定外の状態の可能性; spec={spec!r})。",
            file=sys.stderr,
        )
        return 1

    resolved_origin = os.path.realpath(spec.origin)
    if not resolved_origin.startswith(expected_dir + os.sep):
        print(
            "FATAL: ai_asset_platform が現在のcheckout以外から解決されました。\n"
            f"  resolved origin = {resolved_origin}\n"
            f"  expected dir    = {expected_dir}",
            file=sys.stderr,
        )
        return 1

    # This project's ai_asset_platform is a regular package with
    # submodules (ai_asset_platform.brokers.xxx etc.), so it must have
    # search locations -- a single-file root-level `ai_asset_platform.py`
    # shadow would resolve with submodule_search_locations=None and is
    # rejected here rather than accepted as "close enough".
    search_locations = spec.submodule_search_locations
    if not search_locations:
        print(
            "FATAL: ai_asset_platform がpackageとして解決されません "
            f"(submodule_search_locations が空; origin={resolved_origin})。",
            file=sys.stderr,
        )
        return 1

    for location in search_locations:
        resolved_location = os.path.realpath(location)
        if resolved_location != expected_dir and not resolved_location.startswith(
            expected_dir + os.sep
        ):
            print(
                "FATAL: ai_asset_platform の submodule search location が "
                "現在のcheckout以外を含んでいます。\n"
                f"  location     = {resolved_location}\n"
                f"  expected dir = {expected_dir}",
                file=sys.stderr,
            )
            return 1

    # Only now -- import origin and search locations already confirmed to
    # be exactly this checkout's src/ai_asset_platform/ -- actually import
    # it, as a plain sanity check that it imports without error. This is
    # not part of the safety judgment above; it is already safe by here.
    try:
        import ai_asset_platform  # noqa: F401 - imported for the side effect of exercising it
    except Exception as exc:  # noqa: BLE001 - fail-closed diagnostic, any import failure is fatal
        print(
            f"FATAL: ai_asset_platform の import に失敗しました（checkout確認後）: {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"OK: ai_asset_platform は現在のcheckoutへ解決しました: {resolved_origin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
