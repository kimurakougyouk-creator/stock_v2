#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_ASSET_PLATFORM_ROOT:-$HOME/stock_v2_latest}"
cd "$ROOT"

# Keep the attested source tree bytecode-free for every subsequent Python process.
export PYTHONDONTWRITEBYTECODE=1

persist_shell_blocked_decision() {
  local report="results/strategy_promotion_decision_latest.json"
  local temporary="${report}.tmp"
  mkdir -p results
  cat > "$temporary" <<EOF
{
  "schema_version": 1,
  "status": "PROMOTION_POLICY_BLOCKED",
  "policy_version": "UNAVAILABLE",
  "source_sha": null,
  "strategy_source_sha": null,
  "checked_at": "$(date -u +'%Y-%m-%dT%H:%M:%S+00:00')",
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
  mv "$temporary" "$report"
}

# Any wrapper failure must invalidate a previously persisted PASS before exit.
trap 'persist_shell_blocked_decision' ERR

# Fail closed before activating the venv or importing repository Python.
bash scripts/verify_strategy_source_clean.sh

if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No Paper or Live order was sent."
  persist_shell_blocked_decision
  exit 2
fi

# shellcheck disable=SC1091
source .venv/bin/activate
unset PYTHONPATH
bash scripts/ensure_exact_checkout_runtime.sh

pytest -q \
  tests/test_strategy_promotion_policy.py \
  tests/test_strategy_source_attestation.py

# Replace any stale PASS with a current fail-closed placeholder before the
# evaluator starts. A completed evaluator run atomically replaces this with its
# detailed PASS/BLOCKED record. Disable the ERR trap for the final evaluator so
# a legitimate detailed BLOCKED result (exit 1) is not overwritten.
persist_shell_blocked_decision
trap - ERR
python -m ai_asset_platform.reports.strategy_promotion_policy
