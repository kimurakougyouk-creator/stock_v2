"""Pair the known SPY Paper close with its exact recovered BUY for audit accounting.

This module is calculation-only. It never connects to IBKR and never sends,
changes, or cancels orders. It exists to preserve fail-closed accounting while
still allowing one already-closed SPY Paper round trip to be valued when the BUY
record is missing historical FX but the matching SELL carries explicit FX.
"""
from __future__ import annotations

from copy import deepcopy


class PairedSpyCloseAccountingError(ValueError):
    pass


def _is_spy_fill(row: dict, side: str) -> bool:
    return (
        isinstance(row, dict)
        and str(row.get("mode", "")).strip().upper() == "IBKR_PAPER"
        and str(row.get("status", "")).strip().upper() == "FILLED"
        and str(row.get("ticker", "")).strip().upper() == "SPY"
        and str(row.get("side", "")).strip().upper() == side
        and int(row.get("shares", 0) or 0) == 1
        and str(row.get("currency", "")).strip().upper() == "USD"
    )


def enrich_closed_spy_round_trip(records: list[dict]) -> list[dict]:
    """Return a copy with BUY FX filled only from the unique matching SELL FX.

    This is permitted only when there is exactly one one-share USD SPY BUY and
    exactly one one-share USD SPY SELL, the broker execution ids differ, the BUY
    lacks FX, and the SELL has positive explicit FX. No value is guessed from
    ticker, current market data, or another symbol.
    """
    rows = [deepcopy(row) for row in records]
    buys = [row for row in rows if _is_spy_fill(row, "BUY")]
    sells = [row for row in rows if _is_spy_fill(row, "SELL")]
    if len(buys) != 1 or len(sells) != 1:
        return rows
    buy, sell = buys[0], sells[0]
    if buy.get("fx_to_account_rate") not in (None, ""):
        return rows
    try:
        sell_fx = float(sell.get("fx_to_account_rate"))
    except (TypeError, ValueError):
        return rows
    if sell_fx <= 0:
        return rows
    buy_ids = {str(x).strip() for x in list(buy.get("broker_exec_ids") or []) if str(x).strip()}
    sell_ids = {str(x).strip() for x in list(sell.get("broker_exec_ids") or []) if str(x).strip()}
    if not buy_ids or not sell_ids or buy_ids & sell_ids:
        raise PairedSpyCloseAccountingError("SPY BUY/SELL broker execution identity is unsafe")
    buy["fx_to_account_rate"] = sell_fx
    buy["fx_accounting_source"] = "paired-close-sell-explicit-fx"
    return rows
