#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git switch main
git pull --ff-only origin main
source .venv/bin/activate
python -m pytest -q
AI_ASSET_ENABLE_IBKR_PAPER=1 IBKR_OPTION_E2E_CONFIRM="${IBKR_OPTION_E2E_CONFIRM:-}" python -m ai_asset_platform.brokers.ibkr_option_paper_roundtrip
AI_ASSET_ENABLE_IBKR_PAPER=1 python -m ai_asset_platform.accounting.options_postfill_audit
