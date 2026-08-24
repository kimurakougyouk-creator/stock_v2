#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
cd "$REPO_DIR"

git switch main >/dev/null
git pull --ff-only origin main

if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No order was sent and no ledger file was changed."
  exit 2
fi

if [[ "${IBKR_AAPL_RESET_CONFIRM:-}" != "YES_SELL_EXACTLY_THREE_AAPL_PAPER_TO_FLAT" ]]; then
  echo "BLOCKED: exact AAPL Paper reset confirmation is missing. No order was sent."
  exit 2
fi

source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
# This dedicated wrapper is the explicit Paper-only opt-in. The platform's
# Live Trading flags remain hard-disabled in PlatformSettings and are not
# changed here.
export AI_ASSET_ENABLE_IBKR_PAPER=1

python -m pytest -q
python -m ai_asset_platform.brokers.ibkr_aapl_flat_reset
