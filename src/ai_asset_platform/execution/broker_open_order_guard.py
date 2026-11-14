"""Fail-closed broker open-order guard for IBKR Paper execution.

``ibkr.py``'s ``place_order_and_await_fill`` already blocks re-sending the
exact same ``order_intent_id`` (in-memory, and via a filesystem lock that
survives a process restart). That is not the same protection as blocking a
*new* ``order_intent_id`` for a symbol that still has an earlier order
resting, unconfirmed, at the broker: a timed-out/UNKNOWN attempt is never
auto-resent by this process, but a later natural signal for the same symbol
(a different calendar day, a different order_intent_id) is not aware of it,
because ``broker_position_guard.py`` only reconciles *filled* positions, not
open orders. ``reqAllOpenOrders`` also returns working orders placed under
any client id, not only this session's own, so a resting order from an
earlier, separate connection would otherwise be invisible to this check.

This module is read-only: it only calls ``preview_ibkr_paper_all_open_orders``
(``reqAllOpenOrders``) and never creates, changes, cancels, or transmits an
order.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_all_open_orders_snapshot import (
    IbkrAllOpenOrdersSnapshot,
    preview_ibkr_paper_all_open_orders,
)


@dataclass(frozen=True)
class OpenOrderGuardResult:
    allowed: bool
    reason: str
    ticker: str
    symbol: str
    matching_order_ids: tuple[int, ...]


def evaluate_open_order_guard(
    *,
    ticker: str,
    symbol: str,
    snapshot: IbkrAllOpenOrdersSnapshot | None = None,
) -> OpenOrderGuardResult:
    """Block a new order when one is already open at the broker for ``symbol``."""
    normalized_ticker = str(ticker).strip().upper()
    normalized_symbol = str(symbol).strip().upper()
    if not normalized_ticker or not normalized_symbol:
        return OpenOrderGuardResult(
            False, "invalid order identity for open order guard", normalized_ticker, normalized_symbol, ()
        )

    broker_snapshot = snapshot if snapshot is not None else preview_ibkr_paper_all_open_orders()
    if not broker_snapshot.ready:
        return OpenOrderGuardResult(
            False, "broker open-order snapshot is not ready", normalized_ticker, normalized_symbol, ()
        )

    matching = tuple(
        sorted(
            order.order_id
            for order in broker_snapshot.orders
            if str(order.symbol).strip().upper() == normalized_symbol
        )
    )
    if matching:
        return OpenOrderGuardResult(
            False,
            f"an open order already exists at the broker for this symbol (order_id={list(matching)})",
            normalized_ticker,
            normalized_symbol,
            matching,
        )
    return OpenOrderGuardResult(
        True, "no open order exists at the broker for this symbol", normalized_ticker, normalized_symbol, ()
    )
