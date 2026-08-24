#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
CYCLES="${IBKR_SOAK_CYCLES:-3}"
INTERVAL_SECONDS="${IBKR_SOAK_INTERVAL_SECONDS:-60}"
LIMIT_PRICE="${IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE:-770.00}"
LOG_DIR="$REPO_DIR/results"
LOG_FILE="$LOG_DIR/ibkr_readonly_soak_latest.log"

cd "$REPO_DIR"
git switch main >/dev/null
git pull --ff-only origin main

if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No order was sent."
  exit 2
fi

if ! [[ "$CYCLES" =~ ^[0-9]+$ ]] || (( CYCLES < 2 || CYCLES > 20 )); then
  echo "BLOCKED: IBKR_SOAK_CYCLES must be an integer from 2 to 20. No order was sent."
  exit 2
fi
if ! [[ "$INTERVAL_SECONDS" =~ ^[0-9]+$ ]] || (( INTERVAL_SECONDS < 1 || INTERVAL_SECONDS > 3600 )); then
  echo "BLOCKED: IBKR_SOAK_INTERVAL_SECONDS must be an integer from 1 to 3600. No order was sent."
  exit 2
fi

source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
mkdir -p "$LOG_DIR"
: > "$LOG_FILE"

# Regression tests run in the normal default-safe environment. This wrapper
# never supplies Paper transmission confirmation or Live Trading unlock flags.
python -m pytest -q | tee -a "$LOG_FILE"

for ((cycle=1; cycle<=CYCLES; cycle++)); do
  {
    echo "===== IBKR READ-ONLY SOAK CYCLE $cycle/$CYCLES $(date -Is) ====="
  } | tee -a "$LOG_FILE"

  set +e
  IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE="$LIMIT_PRICE" bash ./ibkr_auto.sh 2>&1 | tee -a "$LOG_FILE"
  status=${PIPESTATUS[0]}
  set -e

  if [[ "$status" -ne 0 ]]; then
    echo "SOAK RESULT: FAIL at cycle $cycle. No order confirmation was supplied." | tee -a "$LOG_FILE"
    echo "REAL ORDER SENT BY SOAK WRAPPER: False" | tee -a "$LOG_FILE"
    exit "$status"
  fi

  if (( cycle < CYCLES )); then
    sleep "$INTERVAL_SECONDS"
  fi
done

echo "SOAK RESULT: PASS ($CYCLES consecutive read-only cycles)" | tee -a "$LOG_FILE"
echo "REAL ORDER SENT BY SOAK WRAPPER: False" | tee -a "$LOG_FILE"
echo "SOAK LOG: $LOG_FILE"
