"""CLI for the explicitly gated SPY Overnight Paper E2E pilot."""
from __future__ import annotations

import os

from ai_asset_platform.brokers.ibkr_overnight_paper_e2e import (
    run_spy_overnight_paper_e2e,
)


def main() -> int:
    raw_price = os.getenv("IBKR_OVERNIGHT_E2E_LIMIT_PRICE", "").strip()
    if not raw_price:
        print("IBKR_OVERNIGHT_E2E_LIMIT_PRICE is required. No order was attempted.")
        return 2
    try:
        price = float(raw_price)
    except ValueError:
        print("IBKR_OVERNIGHT_E2E_LIMIT_PRICE must be numeric. No order was attempted.")
        return 2
    if price <= 0:
        print("IBKR_OVERNIGHT_E2E_LIMIT_PRICE must be positive. No order was attempted.")
        return 2

    result = run_spy_overnight_paper_e2e(limit_price=price)
    print("===== IBKR SPY OVERNIGHT PAPER E2E =====")
    print("ATTEMPTED               :", result.attempted)
    print("REASON                  :", result.reason)
    print("ORDER INTENT ID         :", result.order_intent_id)
    if result.whatif is not None:
        print("WHATIF READY             :", result.whatif.ready)
        print("PRIMARY EXCHANGE         :", result.whatif.primary_exchange)
        print("WHATIF REAL ORDER SENT   :", result.whatif.order_sent)
    broker = result.broker_result
    if broker is not None:
        print("PAPER SENT               :", getattr(broker, "sent", None))
        print("ORDER ID                 :", getattr(broker, "order_id", None))
        print("TERMINAL                 :", getattr(broker, "reached_terminal", None))
        print("TIMEOUT                  :", getattr(broker, "timed_out", None))
        print("IB STATUS                :", getattr(broker, "last_known_status", None))
        print("FILLED QUANTITY          :", getattr(broker, "filled_quantity", None))
        print("AVG FILL PRICE           :", getattr(broker, "avg_fill_price", None))
        print("ERRORS                   :", getattr(broker, "errors", None))
    print("CONFIRMED FILL PERSISTED :", result.confirmed_fill_persisted)
    # Exit 0 means a confirmed fill was persisted. A safe no-attempt/uncertain
    # result is nonzero and must never trigger an automatic retry.
    return 0 if result.confirmed_fill_persisted else 1


if __name__ == "__main__":
    raise SystemExit(main())
