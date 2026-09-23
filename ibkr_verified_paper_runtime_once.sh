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

/usr/bin/git switch main
/usr/bin/git pull --ff-only origin main

run_clean /bin/bash --noprofile --norc scripts/verify_strategy_source_clean.sh

VENV_PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "BLOCKED: .venv/bin/python is missing. No Paper or Live order was sent."
  exit 2
fi

run_clean AI_ASSET_PYTHON_BIN="$VENV_PYTHON" \
  /bin/bash --noprofile --norc scripts/ensure_exact_checkout_runtime.sh

run_clean "$VENV_PYTHON" -m pytest -q \
  tests/test_ibkr_verified_paper_runtime.py \
  tests/test_paper_trading_runner.py \
  tests/test_verified_paper_scan.py \
  tests/test_ibkr_restart_idempotency.py \
  tests/test_ibkr_broker_recovery.py \
  tests/test_ibkr_broker_reconnect_order_safety.py

run_clean \
  AI_ASSET_ENABLE_IBKR_PAPER=1 \
  AI_ASSET_VERIFIED_PAPER_RUNTIME_CONFIRM=RUN_VERIFIED_PAPER_ONLY \
  "$VENV_PYTHON" -m ai_asset_platform.execution.ibkr_verified_paper_runtime