#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_ASSET_PLATFORM_ROOT:-$HOME/stock_v2_latest}"
cd "$ROOT"

git switch main
git pull --ff-only origin main

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

pytest -q tests/test_ibkr_verified_derivative_ledger_cleanup.py

AI_ASSET_ALLOW_VERIFIED_DERIVATIVE_LEDGER_CLEANUP=1 \
  python -m ai_asset_platform.brokers.ibkr_verified_derivative_ledger_cleanup_cli

printf '%s\n' "REAL ORDER SENT BY CLEANUP WRAPPER: False"
