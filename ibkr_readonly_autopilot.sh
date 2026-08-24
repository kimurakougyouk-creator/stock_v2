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
    git pull --ff-only origin main
    if [[ -f .venv/bin/activate ]]; then
      source .venv/bin/activate
      export PYTHONPATH="$PWD/src:$PWD"
      bash ./ibkr_auto.sh
    else
      echo "SKIP: .venv/bin/activate not found. No order was sent."
    fi
    echo "REAL ORDER SENT: False"
  } >>"$LOG_FILE" 2>&1 || true
  sleep "$INTERVAL_SECONDS"
done
