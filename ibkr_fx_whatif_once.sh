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

required=(
  IBKR_FX_WHATIF_BASE
  IBKR_FX_WHATIF_QUOTE
  IBKR_FX_WHATIF_EXCHANGE
  IBKR_FX_WHATIF_SIDE
  IBKR_FX_WHATIF_QUANTITY_MODE
  IBKR_FX_WHATIF_QUANTITY
  IBKR_FX_WHATIF_LIMIT_PRICE
)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "BLOCKED: $name is required. No order was sent."
    exit 2
  fi
done

source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"

# Run the full default-safe regression suite before contacting IBKR.
python -m pytest -q

# This module may submit exactly one IBKR whatIf=True preview request.
# It contains no real-order mode and no Live Trading unlock.
python -m ai_asset_platform.brokers.ibkr_fx_whatif
