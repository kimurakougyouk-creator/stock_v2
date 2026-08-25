#!/usr/bin/env bash
set -uo pipefail

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

failures=0

run_readonly_step() {
  local name="$1"
  shift
  echo "===== READ-ONLY STEP: $name ====="
  if "$@"; then
    echo "STEP RESULT               : PASS ($name)"
  else
    local rc=$?
    echo "STEP RESULT               : BLOCKED ($name, exit=$rc)"
    failures=$((failures + 1))
  fi
}

# Run every read-only check even when an earlier one fails, so one product
# cannot hide later audit evidence. No Paper confirmation or Live enable flag
# is supplied anywhere in this wrapper.
run_readonly_step "pytest" python -m pytest -q
run_readonly_step "stock-etf-global-stock" python -m ai_asset_platform.brokers.ibkr_final_completion_audit
run_readonly_step "futures-postfill" python -m ai_asset_platform.accounting.futures_postfill_audit
run_readonly_step "options-postfill" python -m ai_asset_platform.accounting.options_postfill_audit
run_readonly_step "crypto-visibility" python -m ai_asset_platform.brokers.ibkr_crypto_readonly_audit

echo "===== ALL READ-ONLY COMPLETION AUDITS FINISHED ====="
echo "READ-ONLY FAILED STEPS     : $failures"
echo "FINAL READ-ONLY GATE       : $([[ $failures -eq 0 ]] && echo PASS || echo BLOCKED)"
echo "REAL ORDER SENT BY WRAPPER : False"
echo "LIVE ORDER SENT BY WRAPPER : False"

if [[ $failures -eq 0 ]]; then
  exit 0
fi
exit 2
