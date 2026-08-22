"""Read-only terminal-state audit for the existing IBKR Paper order 6.

Never places, modifies, cancels, or retries an order. It asks IBKR for current
open orders and execution history, then classifies only observed evidence.
"""
from __future__ import annotations

import time

from ibapi.execution import ExecutionFilter

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter

TARGET_ORDER_ID = 6
TARGET_QUANTITY = 100.0
INFO_CODES = {2104, 2106, 2107, 2158}


def classify(open_order: dict | None, executions: list[dict]) -> str:
    executed = sum(float(e.get("shares", 0)) for e in executions)
    if executed >= TARGET_QUANTITY:
        return "FILLED_EXECUTION_CONFIRMED"
    if open_order is not None:
        return "WAIT_NO_RESEND"
    if executed > 0:
        return "PARTIAL_EXECUTION_NOT_OPEN_VERIFY"
    return "NOT_OPEN_TERMINAL_UNCONFIRMED"


def main() -> None:
    print("===== IBKR ORDER 6 TERMINAL AUDIT =====")
    print("MODE      : READ ONLY")
    print("NEW ORDER : DISABLED")
    print("MODIFY    : DISABLED")
    print("CANCEL    : DISABLED")
    print("TARGET ID :", TARGET_ORDER_ID)

    broker = IbkrBrokerAdapter(enable_paper_order_transmission=False)
    try:
        if not broker.connect(connect_timeout=10.0):
            print("RESULT    : BLOCKED_NOT_CONNECTED")
            raise SystemExit(2)

        client = broker._session.client
        client.reqOpenOrders()
        client.reqExecutions(9006, ExecutionFilter())
        time.sleep(4.0)

        open_order = client.open_orders.get(TARGET_ORDER_ID)
        executions = [e for e in client.executions if e.get("order_id") == TARGET_ORDER_ID]
        relevant_errors = [e for e in client.errors if int(e.get("code", 0)) not in INFO_CODES]

        print("OPEN      :", open_order is not None)
        print("OPEN DATA :", open_order)
        print("EXECUTIONS:", executions)
        print("EXEC SHARES:", sum(float(e.get("shares", 0)) for e in executions))
        print("ACTION    :", classify(open_order, executions))
        print("ERRORS    :", relevant_errors)
        print("NEW ORDER SENT : False")
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
