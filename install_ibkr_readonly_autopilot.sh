#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
UNIT_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$UNIT_DIR/ibkr-readonly-autopilot.service"

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
Environment=IBKR_REPO_DIR=$REPO_DIR
Environment=IBKR_AUTOPILOT_INTERVAL_SECONDS=300

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ibkr-readonly-autopilot.service

echo "IBKR read-only autopilot installed and started."
echo "This service only runs ibkr_auto.sh; it does not approve or send Paper/Live orders."
