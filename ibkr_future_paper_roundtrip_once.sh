#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
cd "$REPO_DIR"

git switch main >/dev/null
git pull --ff-only origin main

if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No order was sent."
  exit 2
fi

if [[ "${IBKR_FUTURE_E2E_CONFIRM:-}" != "YES_BUY_AND_SELL_ONE_ESU6_PAPER_TO_FLAT" ]]; then
  echo "BLOCKED: exact ESU6 Paper E2E confirmation is missing. No order was sent."
  exit 2
fi

source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"

# Regression suite remains in the normal default-safe environment.
python -m pytest -q

# Explicit Paper opt-in applies only to this single controlled E2E process.
# Live Trading remains disabled and cannot be unlocked by this wrapper.
AI_ASSET_ENABLE_IBKR_PAPER=1 \
python -m ai_asset_platform.brokers.ibkr_future_paper_roundtrip
