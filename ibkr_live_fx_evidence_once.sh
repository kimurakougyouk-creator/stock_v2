#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_ASSET_PLATFORM_ROOT:-$HOME/stock_v2_latest}"
cd "$ROOT"

if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No Paper or Live order was sent."
  exit 2
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"

pytest -q tests/test_ibkr_live_fx_evidence.py
AI_ASSET_LIVE_READONLY_CONFIRM=READ_LIVE_ACCOUNT_ONLY \
  python -m ai_asset_platform.brokers.ibkr_live_fx_evidence
