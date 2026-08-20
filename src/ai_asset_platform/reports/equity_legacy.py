"""Bridge the durable legacy paper-order ledger into total-asset equity history."""

from __future__ import annotations

from typing import Iterable, Mapping

from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.reports.equity_history import EquityPoint, replay_fills_to_equity


def legacy_orders_to_equity(
    orders: Iterable[dict],
    *,
    initial_cash: float,
    market_prices: Mapping[str, float] | None = None,
) -> list[EquityPoint]:
    normalized: list[tuple[str, FillResult]] = []
    latest_prices: dict[str, float] = dict(market_prices or {})
    seen_without_intent = 0

    for order in orders:
        try:
            side = OrderSide(str(order["side"]).upper())
            ticker = str(order["ticker"])
            shares = int(order["shares"])
            price = float(order["reference_price"])
        except (KeyError, TypeError, ValueError):
            continue
        if shares <= 0 or price <= 0:
            continue

        intent = str(order.get("order_intent_id") or "").strip()
        if not intent:
            seen_without_intent += 1
            intent = f"legacy:{seen_without_intent}:{ticker}:{side.value}:{shares}:{price:.8f}"

        latest_prices.setdefault(ticker, price)
        normalized.append(
            (
                intent,
                FillResult(
                    order_id=intent,
                    symbol=ticker,
                    side=side,
                    quantity=shares,
                    fill_price=price,
                ),
            )
        )

    return replay_fills_to_equity(
        initial_cash=initial_cash,
        fills=normalized,
        market_prices=latest_prices,
    )
