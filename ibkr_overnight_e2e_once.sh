#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
LIMIT_PRICE="${IBKR_OVERNIGHT_E2E_LIMIT_PRICE:-760}"
WAIT_SECONDS="${IBKR_TWS_WAIT_SECONDS:-180}"
ALLOW="${AI_ASSET_ALLOW_ONE_OVERNIGHT_PAPER_E2E:-false}"
LOG_DIR="$REPO_DIR/results"
LATEST_LOG="$LOG_DIR/ibkr_overnight_e2e_latest.log"

case "${ALLOW,,}" in
  1|true|yes|on) ;;
  *)
    echo "SAFE STOP: explicit one-time Overnight Paper E2E approval is missing."
    echo "No order was attempted."
    exit 2
    ;;
esac

cd "$REPO_DIR"

# Preserve all local runtime artifacts; update source only by fast-forward.
git switch main >/dev/null
git pull --ff-only origin main

if [[ ! -f .venv/bin/activate ]]; then
  echo "ERROR: .venv/bin/activate not found. No order was attempted."
  exit 2
fi
source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
mkdir -p "$LOG_DIR"

# Wait for the user's local Paper endpoint; no broker request/order during wait.
python - "$WAIT_SECONDS" <<'PY'
import socket, sys, time
wait = max(0, int(sys.argv[1]))
deadline = time.monotonic() + wait
while True:
    for port in (4002, 7497):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                print(f"IBKR Paper endpoint detected on port {port}")
                raise SystemExit(0)
        except OSError:
            pass
    if time.monotonic() >= deadline:
        print("ERROR: IBKR Paper endpoint was not detected before timeout. No order was attempted.")
        raise SystemExit(3)
    time.sleep(2)
PY

# These process-local flags enable Paper only. The Python E2E has independent
# Live locks, session-hours gate, integrated non-order checkpoint, durable
# session intent-id, and no automatic retry on uncertain/timeout state.
export AI_ASSET_ENABLE_IBKR_PAPER=true
export AI_ASSET_ENABLE_IBKR_OVERNIGHT_E2E=true

set +e
IBKR_OVERNIGHT_E2E_LIMIT_PRICE="$LIMIT_PRICE" \
python -m ai_asset_platform.brokers.ibkr_overnight_paper_e2e_cli 2>&1 | tee "$LATEST_LOG"
status=${PIPESTATUS[0]}
set -e

echo "E2E LOG: $LATEST_LOG"
exit "$status"
