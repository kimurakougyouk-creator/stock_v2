#!/usr/bin/env bash
set -euo pipefail
cd "${IBKR_REPO_DIR:-$HOME/stock_v2_latest}"
git switch main >/dev/null
git pull --ff-only origin main
source .venv/bin/activate
export PYTHONPATH="$PWD/src:$PWD"
python -m pytest -q
python -m ai_asset_platform.accounting.futures_postfill_audit
python -m ai_asset_platform.brokers.ibkr_option_chain_discovery
