#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
PRICE="${IBKR_OVERNIGHT_CLOSE_LIMIT_PRICE:-}"
CONFIRM="${IBKR_OVERNIGHT_CLOSE_CONFIRM:-}"

cd "$REPO_DIR"
git switch main >/dev/null
git pull --ff-only origin main

if [[ "$CONFIRM" != "YES_CLOSE_ONE_SPY_PAPER" ]]; then
  echo "BLOCKED: set IBKR_OVERNIGHT_CLOSE_CONFIRM=YES_CLOSE_ONE_SPY_PAPER to approve one Paper SELL. No order was sent."
  exit 2
fi
if [[ -z "$PRICE" ]]; then
  echo "BLOCKED: IBKR_OVERNIGHT_CLOSE_LIMIT_PRICE is required. No order was sent."
  exit 2
fi
if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No order was sent."
  exit 2
fi

source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
export AI_ASSET_ENABLE_IBKR_PAPER=true
export AI_ASSET_ENABLE_IBKR_OVERNIGHT_CLOSE_E2E=true
export IBKR_OVERNIGHT_CLOSE_LIMIT_PRICE="$PRICE"

python -m ai_asset_platform.brokers.ibkr_overnight_close_e2e
