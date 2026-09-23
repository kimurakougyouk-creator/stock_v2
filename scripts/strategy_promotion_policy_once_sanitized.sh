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

persist_shell_blocked_decision() {
  local report="results/strategy_promotion_decision_latest.json"
  local temporary="${report}.tmp"
  /usr/bin/mkdir -p results
  /usr/bin/cat > "$temporary" <<EOF
{
  "schema_version": 1,
  "status": "PROMOTION_POLICY_BLOCKED",
  "policy_version": "UNAVAILABLE",
  "source_sha": null,
  "strategy_source_sha": null,
  "checked_at": "$(/usr/bin/date -u +'%Y-%m-%dT%H:%M:%S+00:00')",
  "promotion_policy_passed": false,
  "normal_live_strategy_deployment_allowed": false,
  "blockers": ["strategy promotion operational wrapper failed before a current decision completed"],
  "observed_closed_trades": null,
  "observed_net_profit_account_currency": null,
  "observed_maximum_drawdown_account_currency": null,
  "observed_win_rate": null,
  "observed_profit_factor": null,
  "observed_observation_span_seconds": null,
  "observed_evidence_age_seconds": null,
  "paper_evidence_only": true,
  "broker_connection_used": false,
  "order_sent": false,
  "live_order_sent": false,
  "live_trading": "PROHIBITED"
}
EOF
  /usr/bin/mv "$temporary" "$report"
}

trap 'persist_shell_blocked_decision' ERR

if ! run_clean /bin/bash --noprofile --norc scripts/verify_strategy_source_clean.sh; then
  persist_shell_blocked_decision
  exit 2
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "BLOCKED: .venv is missing. No Paper or Live order was sent."
  persist_shell_blocked_decision
  exit 2
fi

run_isolated scripts/verify_exact_checkout_import.py

run_isolated -m pytest -q \
  tests/test_strategy_promotion_policy.py \
  tests/test_strategy_source_attestation.py

persist_shell_blocked_decision
trap - ERR
run_isolated -m ai_asset_platform.reports.strategy_promotion_policy
