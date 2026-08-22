#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
LIMIT_PRICE="${IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE:-760}"
WAIT_SECONDS="${IBKR_TWS_WAIT_SECONDS:-180}"
LOG_DIR="$REPO_DIR/results"
LATEST_LOG="$LOG_DIR/ibkr_operator_checkpoint_latest.log"
RECONCILE_LOG="$LOG_DIR/ibkr_execution_reconcile_latest.log"

cd "$REPO_DIR"

# Preserve local runtime artifacts. Only fast-forward main; never reset, clean,
# stash, delete, or commit local files automatically.
git switch main >/dev/null
git pull --ff-only origin main

if [[ ! -f .venv/bin/activate ]]; then
  echo "ERROR: .venv/bin/activate not found. No order was sent."
  exit 2
fi

source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
mkdir -p "$LOG_DIR"

# Wait for either Paper endpoint. No broker request is made during this wait.
python - "$WAIT_SECONDS" <<'PY'
import socket, sys, time
wait = max(0, int(sys.argv[1]))
deadline = time.monotonic() + wait
ports = (4002, 7497)
while True:
    for port in ports:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                print(f"IBKR Paper endpoint detected on port {port}")
                raise SystemExit(0)
        except OSError:
            pass
    if time.monotonic() >= deadline:
        print("ERROR: IBKR Paper endpoint was not detected before timeout. No order was sent.")
        raise SystemExit(3)
    time.sleep(2)
PY

# First reconcile broker-confirmed execution evidence into the durable local
# ledger. This never creates/transmits/cancels broker orders. Then run the normal
# fail-closed operator checkpoint against the reconciled local state.
set +e
python -m ai_asset_platform.execution.ibkr_execution_reconcile 2>&1 | tee "$RECONCILE_LOG"
reconcile_status=${PIPESTATUS[0]}
IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE="$LIMIT_PRICE" \
python -m ai_asset_platform.brokers.ibkr_operator_checkpoint 2>&1 | tee "$LATEST_LOG"
checkpoint_status=${PIPESTATUS[0]}
set -e

echo "RECONCILIATION LOG: $RECONCILE_LOG"
echo "CHECKPOINT LOG    : $LATEST_LOG"
if [[ "$reconcile_status" -ne 0 ]]; then
  exit "$reconcile_status"
fi
exit "$checkpoint_status"
