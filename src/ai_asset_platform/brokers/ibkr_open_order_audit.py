"""Read-only audit of current IBKR Paper open orders.

No order placement, modification, cancellation, or retry is performed.
"""
from __future__ import annotations

import time

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter

TARGET_ORDER_ID = 6


def main() -> None:
    print("===== IBKR OPEN ORDER AUDIT =====")
    print("MODE      : READ ONLY")
    print("NEW ORDER : DISABLED")
    print("CANCEL    : DISABLED")
    print("TARGET ID :", TARGET_ORDER_ID)

    broker = IbkrBrokerAdapter(enable_paper_order_transmission=False)
    try:
        if not broker.connect(connect_timeout=10.0):
            print("RESULT    : BLOCKED_NOT_CONNECTED")
            raise SystemExit(2)

        client = broker._session.client
        client.reqOpenOrders()
        time.sleep(3.0)

        order = client.open_orders.get(TARGET_ORDER_ID)
        if order is None:
            print("OPEN      : False")
            print("STATUS    : NOT_IN_OPEN_ORDERS")
            print("ACTION    : VERIFY_EXECUTIONS_OR_TERMINAL_STATE")
        else:
            print("OPEN      : True")
            print("SYMBOL    :", order.get("symbol"))
            print("SIDE      :", order.get("action"))
            print("QUANTITY  :", order.get("quantity"))
            print("TYPE      :", order.get("order_type"))
            print("STATUS    :", order.get("status"))
            print("ACTION    : WAIT_NO_RESEND")

        relevant_errors = [
            e for e in client.errors if int(e.get("code", 0)) not in {2104, 2106, 2107, 2158}
        ]
        print("ERRORS    :", relevant_errors)
        print("NEW ORDER SENT : False")
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
