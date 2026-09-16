#!/usr/bin/env python3
"""Fail-closed check: does `ai_asset_platform` resolve to *this* checkout?

Must be run with cwd at the repository root (both callers already `cd`
there). Exits non-zero on any import failure or path mismatch -- including
when a stale or un-migrated install resolves `ai_asset_platform` to some
other checkout. Never trusts pytest's `pythonpath = src` injection (pytest.ini);
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
corrected to match the real invocation context below before importing
anything, so this check sees exactly what those callers would.
"""
import os
import sys


def main() -> int:
    # Match sys.path[0] to what `python -m ai_asset_platform...` actually
    # uses (cwd), not this script's own directory (`scripts/`) -- see the
    # module docstring. Must happen before the import below.
    sys.path[0] = os.getcwd()

    expected_dir = os.path.realpath(os.path.join(os.getcwd(), "src", "ai_asset_platform"))

    try:
        import ai_asset_platform
    except Exception as exc:  # noqa: BLE001 - fail-closed diagnostic, any import failure is fatal
        print(f"FATAL: ai_asset_platform を通常pythonでimportできません: {exc}", file=sys.stderr)
        return 1

    resolved = os.path.realpath(ai_asset_platform.__file__)
    if not resolved.startswith(expected_dir + os.sep):
        print(
            "FATAL: ai_asset_platform が現在のcheckout以外から解決されました。\n"
            f"  resolved = {resolved}\n"
            f"  expected dir = {expected_dir}",
            file=sys.stderr,
        )
        return 1

    print(f"OK: ai_asset_platform は現在のcheckoutへ解決しました: {resolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
