#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
CONFIRM="${IBKR_SAFE_PAPER_E2E_CONFIRM:-}"
LIMIT_PRICE="${IBKR_OVERNIGHT_E2E_LIMIT_PRICE:-770.00}"

if [[ "$CONFIRM" != "YES_RETIRE_STALE_AND_BUY_ONE_SPY_PAPER" ]]; then
  echo "BLOCKED: explicit one-time Paper E2E approval is missing."
  echo "No local ledger file was changed and no broker order was sent."
  exit 2
fi

cd "$REPO_DIR"
git switch main >/dev/null
git pull --ff-only origin main

if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No local ledger file was changed and no broker order was sent."
  exit 2
fi
source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"

# Repository safety first. A test failure stops before any local ledger mutation
# or Paper order attempt.
python -m pytest -q

# Explicitly retire only stale, incomplete IBKR Paper rows that have no broker
# identity to recover and whose symbol is currently flat at the broker. The
# original row is copied to an audit quarantine file and the full ledger is
# backed up before the active ledger is rewritten. This module never sends an
# order and refuses to guess missing currency/FX evidence.
AI_ASSET_ALLOW_STALE_LEGACY_RETIREMENT=true \
python -m ai_asset_platform.brokers.ibkr_legacy_fill_retirement_cli

# Re-run the full no-transmit operator checkpoint against the now-active ledger.
AI_ASSET_ENABLE_IBKR_PAPER=true \
IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE="$LIMIT_PRICE" \
python -m ai_asset_platform.brokers.ibkr_operator_checkpoint

# Only after tests + retirement + no-transmit checkpoint all pass do we allow
# the existing one-share SPY Overnight Paper E2E path to attempt exactly once.
AI_ASSET_ALLOW_ONE_OVERNIGHT_PAPER_E2E=true \
IBKR_OVERNIGHT_E2E_LIMIT_PRICE="$LIMIT_PRICE" \
bash ./ibkr_overnight_e2e_once.sh
