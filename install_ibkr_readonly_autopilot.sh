#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
UNIT_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$UNIT_DIR/ibkr-readonly-autopilot.service"
PIN_DIR="$HOME/.config/ai-asset-platform"
PIN_FILE="$PIN_DIR/ibkr-readonly-autopilot-pinned-head"

cd "$REPO_DIR"
if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv/bin/activate not found. No order was sent."
  exit 2
fi
if [[ "$(git branch --show-current 2>/dev/null || true)" != "main" ]]; then
  echo "BLOCKED: installer must run from local main. No order was sent."
  exit 2
fi
PINNED_HEAD="$(git rev-parse HEAD 2>/dev/null || true)"
if ! [[ "$PINNED_HEAD" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED: current main revision is invalid. No order was sent."
  exit 2
fi
if ! git diff --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**' || \
   ! git diff --cached --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'; then
  echo "BLOCKED: tracked source differs from current main outside runtime outputs. No order was sent."
  exit 2
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
pytest -q \
  tests/test_ibkr_readonly_autopilot.py \
  tests/test_ibkr_account_snapshot.py \
  tests/test_ibkr_all_open_orders_snapshot.py \
  tests/test_ibkr_paper_operations_monitor.py \
  tests/test_ibkr_paper_operations_monitor_strict.py

mkdir -p "$UNIT_DIR" "$PIN_DIR"
umask 077
pin_tmp="$PIN_FILE.tmp"
printf '%s\n' "$PINNED_HEAD" > "$pin_tmp"
chmod 600 "$pin_tmp"
mv -f "$pin_tmp" "$PIN_FILE"

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
Environment=IBKR_AUTOPILOT_PIN_FILE=$PIN_FILE
Environment=IBKR_AUTOPILOT_PINNED_HEAD=$PINNED_HEAD
Environment=IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS=96
Environment=IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES=10485760
Environment=IBKR_PAPER_MONITOR_EMAIL_ALERTS=auto
Environment=IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS=12

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
# Always replace any already-running older process with the newly tested,
# revision-pinned read-only script. `restart` also starts an inactive service.
systemctl --user enable ibkr-readonly-autopilot.service
systemctl --user restart ibkr-readonly-autopilot.service

echo "IBKR read-only autopilot installed and started."
echo "Pinned audited revision: $PINNED_HEAD"
echo "It monitors reconciliation, all open orders, accounting, and verified-runtime history."
echo "It never pulls or executes new source code unattended."
echo "It never approves, sends, changes, cancels, or retries Paper/Live orders."
