#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_ASSET_PLATFORM_ROOT:-$HOME/stock_v2_latest}"
cd "$ROOT"

git switch main
git pull --ff-only origin main

if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No Paper or Live order was sent."
  exit 2
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"

pytest -q \
  tests/test_ibkr_verified_paper_runtime.py \
  tests/test_paper_trading_runner.py \
  tests/test_verified_paper_scan.py \
  tests/test_ibkr_restart_idempotency.py \
  tests/test_ibkr_broker_recovery.py \
  tests/test_ibkr_broker_reconnect_order_safety.py

AI_ASSET_ENABLE_IBKR_PAPER=1 \
AI_ASSET_VERIFIED_PAPER_RUNTIME_CONFIRM=RUN_VERIFIED_PAPER_ONLY \
  python -m ai_asset_platform.execution.ibkr_verified_paper_runtime
