#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
INTERVAL_SECONDS="${IBKR_AUTOPILOT_INTERVAL_SECONDS:-300}"
MAX_LOG_BYTES="${IBKR_AUTOPILOT_MAX_LOG_BYTES:-5242880}"
LOG_DIR="$REPO_DIR/results"
LOG_FILE="$LOG_DIR/ibkr_readonly_autopilot.log"
ROTATED_LOG_FILE="$LOG_FILE.1"

cd "$REPO_DIR"
mkdir -p "$LOG_DIR"

if ! [[ "$INTERVAL_SECONDS" =~ ^[0-9]+$ ]] || (( INTERVAL_SECONDS < 30 || INTERVAL_SECONDS > 86400 )); then
  echo "BLOCKED: IBKR_AUTOPILOT_INTERVAL_SECONDS must be an integer from 30 to 86400. No order was sent." >&2
  exit 2
fi
if ! [[ "$MAX_LOG_BYTES" =~ ^[0-9]+$ ]] || (( MAX_LOG_BYTES < 1048576 || MAX_LOG_BYTES > 104857600 )); then
  echo "BLOCKED: IBKR_AUTOPILOT_MAX_LOG_BYTES must be an integer from 1048576 to 104857600. No order was sent." >&2
  exit 2
fi

rotate_autopilot_log_if_needed() {
  local current_size=0
  if [[ -f "$LOG_FILE" ]]; then
    current_size="$(wc -c < "$LOG_FILE" 2>/dev/null || printf '0')"
  fi
  if [[ "$current_size" =~ ^[0-9]+$ ]] && (( current_size >= MAX_LOG_BYTES )); then
    mv -f "$LOG_FILE" "$ROTATED_LOG_FILE"
  fi
}

while true; do
  rotate_autopilot_log_if_needed
  {
    echo "===== $(date -Is) IBKR READ-ONLY AUTOPILOT ====="
    # Never run an arbitrary development branch unattended. Local main is
    # mandatory, but origin/main availability is not: a transient GitHub/network
    # outage must not suppress already-installed read-only broker safety checks.
    git switch main
    before_head="$(git rev-parse HEAD)"
    if git pull --ff-only origin main; then
      after_head="$(git rev-parse HEAD)"
      if [[ "$after_head" != "$before_head" ]]; then
        echo "AUTOPILOT UPDATE: main changed; reloading read-only autopilot from the new revision."
        exec /usr/bin/env bash "$REPO_DIR/ibkr_readonly_autopilot.sh"
      fi
    else
      echo "AUTOPILOT UPDATE WARNING: origin/main unavailable; continuing from unchanged local main. No order was sent."
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
