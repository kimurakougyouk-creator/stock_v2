#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
UNIT_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$UNIT_DIR/ibkr-readonly-autopilot.service"

cd "$REPO_DIR"
if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv/bin/activate not found. No order was sent."
  exit 2
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
pytest -q \
  tests/test_ibkr_readonly_autopilot.py \
  tests/test_ibkr_all_open_orders_snapshot.py \
  tests/test_ibkr_paper_operations_monitor.py \
  tests/test_ibkr_paper_operations_monitor_strict.py

mkdir -p "$UNIT_DIR"
cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=IBKR Paper read-only autopilot
After=default.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
ExecStart=/usr/bin/env bash $REPO_DIR/ibkr_readonly_autopilot.sh
Restart=always
RestartSec=15
UMask=0077
Environment=IBKR_REPO_DIR=$REPO_DIR
Environment=IBKR_AUTOPILOT_INTERVAL_SECONDS=300
Environment=IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS=96
Environment=IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES=10485760
Environment=IBKR_PAPER_MONITOR_EMAIL_ALERTS=auto
Environment=IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS=12

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
# Always replace any already-running older process with the newly verified script.
# `restart` also starts the service when it is currently inactive.
systemctl --user enable ibkr-readonly-autopilot.service
systemctl --user restart ibkr-readonly-autopilot.service

echo "IBKR read-only autopilot installed and started."
echo "It monitors reconciliation, all open orders, accounting, and verified-runtime history."
echo "It never approves, sends, changes, cancels, or retries Paper/Live orders."
