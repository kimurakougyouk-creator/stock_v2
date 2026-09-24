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

# Deliberately do not switch/fetch/pull here. Updating the checkout from inside
# an already-running operational body would execute unaudited Git transport
# configuration and could make the in-memory wrapper differ from the attested
# on-disk revision. Checkout updates must complete before this entrypoint starts.
run_clean /bin/bash --noprofile --norc scripts/verify_strategy_source_clean.sh

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "BLOCKED: .venv is missing. No Paper or Live order was sent."
  exit 2
fi

run_isolated scripts/verify_exact_checkout_import.py

run_isolated -m pytest -q \
  tests/test_ibkr_verified_paper_runtime.py \
  tests/test_paper_trading_runner.py \
  tests/test_verified_paper_scan.py \
  tests/test_ibkr_restart_idempotency.py \
  tests/test_ibkr_broker_recovery.py \
  tests/test_ibkr_broker_reconnect_order_safety.py

run_clean \
  AI_ASSET_PLATFORM_ROOT="$ROOT" \
  AI_ASSET_ENABLE_IBKR_PAPER=1 \
  AI_ASSET_VERIFIED_PAPER_RUNTIME_CONFIRM=RUN_VERIFIED_PAPER_ONLY \
  /usr/bin/python3 -I -S "$ROOT/scripts/run_isolated_venv_python.py" \
  -m ai_asset_platform.execution.ibkr_verified_paper_runtime
