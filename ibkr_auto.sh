#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
LIMIT_PRICE="${IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE:-760}"
WAIT_SECONDS="${IBKR_TWS_WAIT_SECONDS:-180}"
LOG_DIR="$REPO_DIR/results"
LATEST_LOG="$LOG_DIR/ibkr_operator_checkpoint_latest.log"
EXECUTION_LOG="$LOG_DIR/ibkr_execution_snapshot_latest.log"
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

# Wait for either Paper endpoint. This removes repeated manual retries while TWS
# or Gateway is still starting. No broker request is made during this wait.
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

# Run one non-real-order checkpoint, a read-only execution snapshot, and then
# reconcile only broker-confirmed executions into the local durable ledger.
# The reconciliation stage never sends/changes/cancels broker orders.
set +e
IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE="$LIMIT_PRICE" \
python -m ai_asset_platform.brokers.ibkr_operator_checkpoint 2>&1 | tee "$LATEST_LOG"
checkpoint_status=${PIPESTATUS[0]}
python -m ai_asset_platform.brokers.ibkr_execution_snapshot 2>&1 | tee "$EXECUTION_LOG"
execution_status=${PIPESTATUS[0]}
if [[ "$execution_status" -eq 0 ]]; then
python - <<'PY' 2>&1 | tee "$RECONCILE_LOG"
from pathlib import Path
import order_manager
from ai_asset_platform.brokers.ibkr_execution_snapshot import preview_ibkr_paper_execution_snapshot
from ai_asset_platform.execution.ibkr_execution_reconcile import reconcile_execution_snapshot_to_ledger

snapshot = preview_ibkr_paper_execution_snapshot()
result = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=order_manager.ORDER_LOG_PATH)
print("===== IBKR PAPER EXECUTION RECONCILIATION =====")
print("SNAPSHOT READY   :", snapshot.ready)
print("RECONCILED COUNT :", result.reconciled_count)
print("SKIPPED COUNT    :", result.skipped_count)
print("ERRORS           :", list(result.errors))
print("REAL ORDER SENT  : False")
raise SystemExit(0 if snapshot.ready and not result.errors else 1)
PY
reconcile_status=${PIPESTATUS[0]}
else
  reconcile_status=1
fi
set -e

echo "CHECKPOINT LOG : $LATEST_LOG"
echo "EXECUTION LOG  : $EXECUTION_LOG"
echo "RECONCILE LOG  : $RECONCILE_LOG"
if [[ "$execution_status" -ne 0 ]]; then
  exit "$execution_status"
fi
if [[ "$reconcile_status" -ne 0 ]]; then
  exit "$reconcile_status"
fi
# The pre-reconciliation checkpoint may correctly be blocked by the divergence
# that this run just repaired, so do not fail solely on that old checkpoint.
exit 0
