#!/usr/bin/env bash
set -euo pipefail

# Human-facing single entrypoint for Issue #255.
#
# This wrapper never creates an authorization and never supplies the final
# consequential confirmation by default. Those values must already exist in
# the environment from the separately approved operator step.
#
# Re-running this same entrypoint after the irreversible campaign marker exists
# is recovery-only: the Python coordinator makes the sender unreachable and
# performs read-only reconciliation only.

ROOT="${AI_ASSET_PLATFORM_ROOT:-$PWD}"
cd "$ROOT"

if [[ ! -f .venv/bin/activate ]]; then
  echo "BLOCKED: .venv is missing. No Live order was sent."
  exit 2
fi

: "${LIVE_PILOT_INTENT_ID:?BLOCKED: LIVE_PILOT_INTENT_ID is required}"
: "${LIVE_PILOT_TICKER:?BLOCKED: LIVE_PILOT_TICKER is required}"
: "${LIVE_PILOT_SIDE:?BLOCKED: LIVE_PILOT_SIDE is required}"
: "${LIVE_PILOT_QUANTITY:?BLOCKED: LIVE_PILOT_QUANTITY is required}"
: "${LIVE_PILOT_LIMIT_PRICE:?BLOCKED: LIVE_PILOT_LIMIT_PRICE is required}"
: "${LIVE_PILOT_NOTIONAL_JPY:?BLOCKED: LIVE_PILOT_NOTIONAL_JPY is required}"
: "${LIVE_PILOT_NONCE:?BLOCKED: LIVE_PILOT_NONCE is required}"
: "${LIVE_PILOT_ACCOUNT_FINGERPRINT:?BLOCKED: LIVE_PILOT_ACCOUNT_FINGERPRINT is required}"
: "${LIVE_PILOT_EXPECTED_COMMIT_SHA:?BLOCKED: LIVE_PILOT_EXPECTED_COMMIT_SHA is required}"

# shellcheck disable=SC1091
source .venv/bin/activate
unset PYTHONPATH
bash scripts/ensure_exact_checkout_runtime.sh

ACTUAL_SHA="$(git rev-parse HEAD)"
if [[ "$ACTUAL_SHA" != "$LIVE_PILOT_EXPECTED_COMMIT_SHA" ]]; then
  echo "BLOCKED: checkout SHA does not match the explicitly approved SHA. No Live order was sent."
  exit 2
fi

python -P -m ai_asset_platform.execution.live_pilot_operational_entrypoint \
  --intent-id "$LIVE_PILOT_INTENT_ID" \
  --ticker "$LIVE_PILOT_TICKER" \
  --side "$LIVE_PILOT_SIDE" \
  --quantity "$LIVE_PILOT_QUANTITY" \
  --limit-price "$LIVE_PILOT_LIMIT_PRICE" \
  --estimated-notional-jpy "$LIVE_PILOT_NOTIONAL_JPY" \
  --nonce "$LIVE_PILOT_NONCE" \
  --account-fingerprint "$LIVE_PILOT_ACCOUNT_FINGERPRINT" \
  --expected-commit-sha "$LIVE_PILOT_EXPECTED_COMMIT_SHA" \
  --final-confirmation "${LIVE_PILOT_FINAL_CONFIRMATION:-}" \
  --live-readonly-confirmation "READ_LIVE_ACCOUNT_ONLY" \
  --repository-root "$ROOT"
