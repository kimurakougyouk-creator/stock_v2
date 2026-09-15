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
"""
import os
import sys


def main() -> int:
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
