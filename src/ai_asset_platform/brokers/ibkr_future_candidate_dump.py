"""Read-only dump of broker-resolved futures candidates.

Used to choose one explicit Paper test contract without inventing expiry,
localSymbol, multiplier, conId, or tick size. No Order is created or sent.
"""
from __future__ import annotations

import os

from ai_asset_platform.brokers.ibkr_future_discovery import discover_ibkr_paper_futures


def main() -> int:
    symbol = os.getenv("IBKR_FUTURE_SYMBOL", "ES").strip().upper()
    exchange = os.getenv("IBKR_FUTURE_EXCHANGE", "CME").strip().upper()
    currency = os.getenv("IBKR_FUTURE_CURRENCY", "USD").strip().upper()

    result = discover_ibkr_paper_futures(
        symbol=symbol,
        exchange=exchange,
        currency=currency,
        timeout=10.0,
    )

    print("===== IBKR PAPER FUTURES CANDIDATE DUMP =====")
    print("CONNECTED       :", result.connected)
    print("ENDPOINT PORT   :", result.endpoint_port)
    print("TARGET          :", f"{symbol}/{exchange}/{currency}")
    print("CANDIDATE COUNT :", len(result.candidates))
    for index, candidate in enumerate(result.candidates, start=1):
        print(
            f"CANDIDATE {index}: "
            f"local_symbol={candidate.local_symbol} "
            f"expiry={candidate.expiry} "
            f"multiplier={candidate.multiplier} "
            f"con_id={candidate.con_id} "
            f"min_tick={candidate.min_tick} "
            f"time_zone={candidate.time_zone_id}"
        )
    print("ERRORS          :", list(result.errors))
    print("REAL ORDER SENT : False")
    print("LIVE ORDER SENT : False")
    return 0 if result.connected and result.candidates and not result.order_sent else 2


if __name__ == "__main__":
    raise SystemExit(main())
