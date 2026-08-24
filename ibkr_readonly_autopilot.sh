#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
INTERVAL_SECONDS="${IBKR_AUTOPILOT_INTERVAL_SECONDS:-300}"
LOG_DIR="$REPO_DIR/results"
LOG_FILE="$LOG_DIR/ibkr_readonly_autopilot.log"

cd "$REPO_DIR"
mkdir -p "$LOG_DIR"

while true; do
  {
    echo "===== $(date -Is) IBKR READ-ONLY AUTOPILOT ====="
    git switch main
    before_head="$(git rev-parse HEAD)"
    git pull --ff-only origin main
    after_head="$(git rev-parse HEAD)"
    if [[ "$after_head" != "$before_head" ]]; then
      echo "AUTOPILOT UPDATE: main changed; reloading read-only autopilot from the new revision."
      exec /usr/bin/env bash "$REPO_DIR/ibkr_readonly_autopilot.sh"
    fi
    if [[ -f .venv/bin/activate ]]; then
      source .venv/bin/activate
      export PYTHONPATH="$PWD/src:$PWD"
      bash ./ibkr_auto.sh || echo "CHECKPOINT NOT READY: read-only checkpoint returned non-zero"
      python -m ai_asset_platform.brokers.ibkr_multiasset_readonly_audit \
        || echo "MULTI-ASSET NOT READY: read-only ContractDetails audit returned non-zero"
    else
      echo "SKIP: .venv/bin/activate not found. No order was sent."
    fi
    echo "REAL ORDER SENT: False"
  } >>"$LOG_FILE" 2>&1 || true
  sleep "$INTERVAL_SECONDS"
done
