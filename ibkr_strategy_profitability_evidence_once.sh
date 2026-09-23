#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_ASSET_PLATFORM_ROOT:-$HOME/stock_v2_latest}"
unset BASH_ENV ENV CDPATH PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH
unset -f git awk bash python pytest env 2>/dev/null || true
export PATH="/usr/local/bin:/usr/bin:/bin"
export PYTHONDONTWRITEBYTECODE=1
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

run_clean /bin/bash --noprofile --norc scripts/verify_strategy_source_clean.sh

VENV_PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "BLOCKED: .venv/bin/python is missing. No Paper or Live order was sent."
  exit 2
fi

run_clean AI_ASSET_PYTHON_BIN="$VENV_PYTHON" \
  /bin/bash --noprofile --norc scripts/ensure_exact_checkout_runtime.sh

run_clean "$VENV_PYTHON" -m pytest -q tests/test_strategy_profitability_evidence.py
run_clean "$VENV_PYTHON" -m ai_asset_platform.reports.strategy_profitability_evidence