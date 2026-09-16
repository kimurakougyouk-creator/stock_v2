#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git switch main
git pull --ff-only origin main
source .venv/bin/activate
unset PYTHONPATH
bash scripts/ensure_exact_checkout_runtime.sh
python -m pytest -q
python -m ai_asset_platform.brokers.ibkr_future_candidate_dump
