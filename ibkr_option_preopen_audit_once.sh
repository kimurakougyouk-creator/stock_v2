#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git switch main
git pull --ff-only origin main
source .venv/bin/activate
python -m pytest -q
AI_ASSET_ENABLE_IBKR_PAPER=1 python -m ai_asset_platform.brokers.ibkr_option_preopen_audit
AI_ASSET_ENABLE_IBKR_PAPER=1 python -m ai_asset_platform.brokers.ibkr_option_permission_preflight
