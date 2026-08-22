#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
CONFIRM="${IBKR_OVERNIGHT_CLOSE_CONFIRM:-}"

cd "$REPO_DIR"
git switch main >/dev/null
git pull --ff-only origin main

if [[ "$CONFIRM" != "YES_CLOSE_ONE_SPY_PAPER" ]]; then
  echo "BLOCKED: set IBKR_OVERNIGHT_CLOSE_CONFIRM=YES_CLOSE_ONE_SPY_PAPER to approve one position-reducing Paper SELL. No order was sent."
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

python -m ai_asset_platform.brokers.ibkr_close_cycle
close_rc=$?

# If a confirmed close was persisted, immediately run the non-order checkpoint
# so broker/local quantity and accounting are re-verified in the same operator action.
if [[ $close_rc -eq 0 ]]; then
  bash ./ibkr_auto.sh
fi

exit $close_rc
