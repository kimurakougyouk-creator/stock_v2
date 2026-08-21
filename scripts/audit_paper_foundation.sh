#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

echo "===== PAPER FOUNDATION AUDIT ====="
echo "Safety: this command does not enable Live Trading or transmit an order."

if [ ! -d .venv ]; then
  echo "ERROR: .venv is missing. Run: bash scripts/setup.sh"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[1/3] Secret scan"
python scripts/check_secrets.py

echo "[2/3] Full pytest"
python -m pytest -q

echo "[3/3] IBKR Paper no-transmit smoke"
python -m ai_asset_platform.brokers.ibkr_paper_smoke_test

echo "===== PAPER FOUNDATION AUDIT COMPLETE ====="
