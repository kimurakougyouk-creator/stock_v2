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

source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"

# Default-safe repository verification. No Paper order confirmation and no Live
# enable flag is provided anywhere in this wrapper.
python -m pytest -q

# Broker/local stock+ETF/global-stock accounting, position flatness and
# reconciliation idempotency.
python -m ai_asset_platform.brokers.ibkr_final_completion_audit

# Product-specific derivative accounting/restart recovery. Read-only only.
python -m ai_asset_platform.accounting.futures_postfill_audit
python -m ai_asset_platform.accounting.options_postfill_audit

# Crypto catalog/API visibility only. This deliberately never promotes account
# permission or Paper trading capability from ContractDetails alone.
python -m ai_asset_platform.brokers.ibkr_crypto_readonly_audit

echo "===== ALL READ-ONLY COMPLETION AUDITS FINISHED ====="
echo "REAL ORDER SENT BY WRAPPER : False"
echo "LIVE ORDER SENT BY WRAPPER : False"
