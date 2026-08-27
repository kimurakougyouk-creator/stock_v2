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
  tests/test_ibkr_all_open_orders_snapshot.py \
  tests/test_ibkr_paper_operations_monitor.py \
  tests/test_ibkr_paper_operations_monitor_strict.py \
  tests/test_ibkr_reconciliation_evidence_audit.py \
  tests/test_ibkr_verified_paper_runtime.py

python -m ai_asset_platform.brokers.ibkr_paper_operations_monitor_strict
