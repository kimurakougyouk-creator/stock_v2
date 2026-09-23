#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_ASSET_PLATFORM_ROOT:-$HOME/stock_v2_latest}"
cd "$ROOT"

# Keep the attested source tree bytecode-free for every subsequent Python process.
export PYTHONDONTWRITEBYTECODE=1

# Fail closed before activating the venv or importing repository Python.
bash scripts/verify_strategy_source_clean.sh

if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No Paper or Live order was sent."
  exit 2
fi

# shellcheck disable=SC1091
source .venv/bin/activate
unset PYTHONPATH
bash scripts/ensure_exact_checkout_runtime.sh

pytest -q tests/test_strategy_profitability_evidence.py
python -m ai_asset_platform.reports.strategy_profitability_evidence