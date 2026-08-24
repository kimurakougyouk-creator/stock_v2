#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git switch main
git pull --ff-only origin main
source .venv/bin/activate
python -m pytest -q
: "${IBKR_FUTURE_SYMBOL:=ES}"
: "${IBKR_FUTURE_EXCHANGE:=CME}"
: "${IBKR_FUTURE_CURRENCY:=USD}"
IBKR_AUDIT_FUTURE_SYMBOL="$IBKR_FUTURE_SYMBOL" \
IBKR_AUDIT_FUTURE_EXCHANGE="$IBKR_FUTURE_EXCHANGE" \
IBKR_AUDIT_FUTURE_CURRENCY="$IBKR_FUTURE_CURRENCY" \
python -m ai_asset_platform.brokers.ibkr_multiasset_readonly_audit
