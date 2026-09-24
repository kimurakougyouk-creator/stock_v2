#!/bin/bash
set -euo pipefail

ROOT="${AI_ASSET_PLATFORM_ROOT:-$HOME/stock_v2_latest}"
cd "$ROOT"

run_clean() {
  /usr/bin/env -i \
    HOME="${HOME:-}" \
    USER="${USER:-}" \
    LOGNAME="${LOGNAME:-}" \
    LANG="${LANG:-C.UTF-8}" \
    PATH="/usr/local/bin:/usr/bin:/bin" \
    PYTHONDONTWRITEBYTECODE=1 \
    "$@"
}

run_isolated() {
  run_clean \
    AI_ASSET_PLATFORM_ROOT="$ROOT" \
    /usr/bin/python3 -I -S "$ROOT/scripts/run_isolated_venv_python.py" "$@"
}

run_clean /bin/bash --noprofile --norc scripts/verify_strategy_source_clean.sh

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "BLOCKED: .venv is missing. No Paper or Live order was sent."
  exit 2
fi

run_isolated scripts/verify_exact_checkout_import.py
run_isolated -m pytest -q tests/test_strategy_profitability_evidence.py
run_isolated -m ai_asset_platform.reports.strategy_profitability_evidence
