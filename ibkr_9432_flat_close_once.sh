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

if [[ "${IBKR_9432_CLOSE_CONFIRM:-}" != "YES_SELL_EXACTLY_100_9432_TSEJ_PAPER_TO_FLAT" ]]; then
  echo "BLOCKED: exact 9432 Paper close confirmation is missing. No order was sent."
  exit 2
fi

source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"

# Regression tests deliberately run before any Paper opt-in is set so the
# repository's default-safe behavior remains tested exactly as shipped.
python -m pytest -q

# Scope Paper enablement only to this single, explicitly confirmed close
# process. No Live Trading enable/unlock flag is supplied here.
AI_ASSET_ENABLE_IBKR_PAPER=1 \
IBKR_9432_CLOSE_CONFIRM="$IBKR_9432_CLOSE_CONFIRM" \
python -m ai_asset_platform.brokers.ibkr_9432_flat_close
