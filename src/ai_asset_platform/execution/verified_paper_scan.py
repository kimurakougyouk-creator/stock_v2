"""Execute analyzed signals through the broker-verified Paper path only.

The legacy signal scanner remains responsible for data/technical/AI analysis and
report generation, but this module owns IBKR Paper execution decisions.  It does
not use the legacy JPY/100-share sizing arithmetic.  Quantity comes exclusively
from broker-verified instrument metadata, while monetary limits are enforced by
the account-currency preflight in the final order callback.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import order_manager
import signal_runner

from ai_asset_platform.core.settings import PlatformSettings, SETTINGS
from ai_asset_platform.execution.signal_order_bridge import (
    verified_paper_test_quantity_for_ticker,
)


OrderExecutor = Callable[[str, str, int, float], dict]


def execute_verified_actions_from_scan(
    scan_result: dict,
    *,
    execute_order: OrderExecutor,
    settings: PlatformSettings = SETTINGS,
) -> dict:
    """Execute only verified BUY/SELL actions from an analysis-only scan.

    The function recomputes confirmed holdings before every action.  Existing
    positions block new BUY exposure.  SELL requires enough confirmed holdings
    for the broker-verified pilot quantity.  Trailing/time stops are retained as
    position-reducing overrides, but unverified quantities are never invented.
    Per-order failures are collected and do not trigger automatic resubmission.
    """
    result = dict(scan_result)
    paper_orders: list[dict] = []
    execution_errors: list[dict[str, str]] = []

    for record in list(scan_result.get("records") or []):
        if not isinstance(record, dict):
            continue
        ticker = str(record.get("Ticker", "")).strip()
        final_signal = str(record.get("FinalSignal", "HOLD")).strip().upper()
        try:
            price = float(record.get("Close"))
        except (TypeError, ValueError):
            if final_signal in {"BUY", "SELL"}:
                execution_errors.append({
                    "ticker": ticker or "UNKNOWN",
                    "error": "actionable signal has no positive reference price",
                })
            continue
        if not ticker or price <= 0:
            continue

        positions = order_manager.get_open_positions()
        held_shares = int(positions.get(ticker, 0))
        if held_shares < 0:
            execution_errors.append({
                "ticker": ticker,
                "error": "confirmed ledger contains a negative position; execution blocked",
            })
            continue

        order_signal = final_signal
        forced_exit = False
        if held_shares > 0:
            highest = order_manager.update_trailing_high_price(
                ticker,
                price,
                held_shares=held_shares,
            )
            trailing_percent = float(getattr(settings, "trailing_stop_percent", 0.0))
            trailing_triggered, _ = signal_runner.evaluate_trailing_stop(
                current_price=price,
                highest_price=highest,
                trailing_stop_percent=trailing_percent,
                held_shares=held_shares,
            )
            holding_days = order_manager.calculate_position_holding_days(ticker)
            max_holding_days = int(getattr(settings, "max_holding_days", 0))
            time_triggered = (
                max_holding_days > 0
                and holding_days is not None
                and holding_days >= max_holding_days
            )
            if trailing_triggered or time_triggered:
                order_signal = "SELL"
                forced_exit = True

        if order_signal not in {"BUY", "SELL"}:
            continue
        if order_signal == "BUY" and held_shares > 0:
            continue
        if order_signal == "SELL" and held_shares <= 0:
            continue

        verified_quantity = verified_paper_test_quantity_for_ticker(ticker)
        if verified_quantity is None:
            execution_errors.append({
                "ticker": ticker,
                "error": "broker-verified Paper quantity is not registered",
            })
            continue
        quantity = int(verified_quantity)
        if quantity <= 0:
            execution_errors.append({
                "ticker": ticker,
                "error": "broker-verified Paper quantity is invalid",
            })
            continue
        if order_signal == "SELL" and held_shares < quantity:
            execution_errors.append({
                "ticker": ticker,
                "error": (
                    "confirmed holdings are smaller than the broker-verified "
                    "Paper SELL quantity"
                ),
            })
            continue

        try:
            paper_order = execute_order(ticker, order_signal, quantity, price)
        except Exception as exc:
            execution_errors.append({"ticker": ticker, "error": str(exc)})
            continue

        enriched = dict(paper_order)
        enriched["forced_exit"] = bool(forced_exit)
        paper_orders.append(enriched)

    result["paper_orders"] = paper_orders
    result["execution_errors"] = execution_errors
    if execution_errors:
        result["errors"] = list(result.get("errors") or []) + execution_errors
    return result
