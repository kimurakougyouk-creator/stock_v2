#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_ASSET_PLATFORM_ROOT:-$HOME/stock_v2_latest}"
cd "$ROOT"

git switch main
git pull --ff-only origin main

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

pytest -q \
  tests/test_ibkr_closed_spy_fx_ledger_repair.py \
  tests/test_paired_spy_close_accounting.py \
  tests/test_ibkr_reconciliation_evidence_audit.py

AI_ASSET_ALLOW_CLOSED_SPY_FX_LEDGER_REPAIR=1 \
  python -m ai_asset_platform.brokers.ibkr_closed_spy_fx_ledger_repair_cli

python -m ai_asset_platform.brokers.ibkr_reconciliation_evidence_audit
IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE="${IBKR_OVERNIGHT_WHATIF_LIMIT_PRICE:-770.00}" \
  bash ./ibkr_auto.sh

printf '%s\n' "REAL ORDER SENT BY CLOSED SPY FX REPAIR WRAPPER: False"
