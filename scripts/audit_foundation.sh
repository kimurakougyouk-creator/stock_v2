#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "ERROR: .venv is missing. Run: bash scripts/setup.sh"
  exit 1
fi

source .venv/bin/activate

echo "===== SECRET SCAN ====="
python scripts/check_secrets.py

echo "===== FULL TEST SUITE ====="
pytest -q

echo "===== IBKR PAPER NO-TRANSMIT SMOKE ====="
python -m ai_asset_platform.brokers.ibkr_paper_smoke_test

echo "===== FOUNDATION AUDIT PASSED ====="
