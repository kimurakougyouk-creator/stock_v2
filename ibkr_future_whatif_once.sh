#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git switch main
git pull --ff-only origin main
source .venv/bin/activate
python -m pytest -q
python - <<'PY'
from ai_asset_platform.brokers.ibkr_future_whatif import preview_ibkr_paper_future_whatif

result = preview_ibkr_paper_future_whatif(
    symbol="ES",
    exchange="CME",
    currency="USD",
    expiry="20260918",
    multiplier="50",
    local_symbol="ESU6",
    con_id=649180671,
    side="BUY",
    quantity=1,
    limit_price=1.0,
    timeout=10.0,
)
print("===== IBKR PAPER FUTURES WHAT-IF =====")
print("CONNECTED             :", result.connected)
print("ENDPOINT PORT         :", result.endpoint_port)
print("TARGET                : ESU6 / CME / USD")
print("EXPIRY                : 20260918")
print("MULTIPLIER            : 50")
print("CON ID                : 649180671")
print("SIDE                  : BUY")
print("QUANTITY              : 1")
print("LIMIT PRICE           : 1.0")
print("PREVIEW RECEIVED      :", result.preview_received)
print("ORDER ID              :", result.order_id)
print("MARGIN CHANGE         :", result.margin_change)
print("COMMISSION            :", result.commission)
print("COMMISSION CURRENCY   :", result.commission_currency)
print("WARNING               :", result.warning)
print("ERRORS                :", list(result.errors))
print("REAL ORDER SENT       :", result.real_order_sent)
print("LIVE ORDER SENT       :", result.live_order_sent)
PY
