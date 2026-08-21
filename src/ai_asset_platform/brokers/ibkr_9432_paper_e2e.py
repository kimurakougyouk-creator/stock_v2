"""Explicit IBKR Paper E2E audit for broker-verified 9432/TSEJ lot size.

This module intentionally bypasses strategy/AI signal generation. It exercises
only the already-audited Paper execution path for 9432 with 100 shares.
Live trading remains prohibited by the underlying configuration and service.

v1 was confirmed NOT_SENT before the lower-level sender guard was corrected.
v2 was SENT but IBKR rejected it with 10311/201 because the stock API redirect
warning precaution was not bypassed.  v3 is the single deliberate retry after
that Paper Gateway precaution was explicitly enabled.  The stable v3 intent
keeps accidental re-runs fail-closed after any real send.
"""
from __future__ import annotations

from pathlib import Path

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.core.asset_classes import AssetClass

SYMBOL = "9432"
QUANTITY = 100
ORDER_INTENT_ID = "9432-paper-e2e-verified-lot-v3"
FILL_STATE_PATH = Path("data/ibkr_9432_paper_e2e_fill_state.json")


def build_instrument() -> InstrumentSpec:
    return InstrumentSpec(
        symbol=SYMBOL,
        asset_class=AssetClass.STOCK,
        exchange="TSEJ",
        currency="JPY",
        verified_paper_test_quantity=QUANTITY,
    )


def main() -> None:
    print("===== 9432.T IBKR PAPER E2E =====")
    print("MODE     : IBKR PAPER ONLY")
    print("SYMBOL   : 9432.T")
    print("SIDE     : BUY")
    print(f"QUANTITY : {QUANTITY}")
    print("INTENT   :", ORDER_INTENT_ID)
    print("LIVE     : DISABLED")

    broker = IbkrBrokerAdapter(
        enable_paper_order_transmission=True,
        fill_state_path=FILL_STATE_PATH,
    )
    try:
        if not broker.connect(connect_timeout=10.0):
            print("RESULT   : BLOCKED_NOT_CONNECTED")
            raise SystemExit(2)

        result = broker.place_order_and_await_fill(
            OrderRequest(SYMBOL, OrderSide.BUY, QUANTITY),
            order_intent_id=ORDER_INTENT_ID,
            instrument=build_instrument(),
            timeout_seconds=30.0,
        )
        print("STATUS   :", result.status)
        print("SENT     :", result.sent)
        print("ORDER ID :", result.order_id)
        print("TERMINAL :", result.reached_terminal)
        print("TIMEOUT  :", result.timed_out)
        print("IB STATUS:", result.last_known_status)
        print("FILLED   :", result.filled_quantity)
        print("AVG PRICE:", result.avg_fill_price)
        print("ERRORS   :", result.errors)
        print("MESSAGE  :", result.message)

        if not (
            result.sent
            and result.reached_terminal
            and result.last_known_status == "Filled"
            and float(result.filled_quantity) == float(QUANTITY)
            and result.avg_fill_price is not None
            and float(result.avg_fill_price) > 0
        ):
            raise SystemExit(3)
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
