"""Reconcile already-confirmed IBKR Paper fill evidence into reporting state.

This module NEVER connects to IBKR and NEVER sends orders. It exists only for
post-fill recovery/audit when a real Paper fill was persisted by IbkrFillRuntime
but the higher-level reporting callback was not used by the diagnostic command.
"""
from __future__ import annotations

import json
from pathlib import Path

from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill


def reconcile_confirmed_fill(
    *,
    fill_state_path: Path,
    order_id: int,
    ticker: str,
    side: str,
    currency: str,
    order_intent_id: str,
    order_log_path: Path,
) -> dict:
    payload = json.loads(fill_state_path.read_text(encoding="utf-8"))
    order_key = str(int(order_id))
    processed = float(payload.get("processed_filled", {}).get(order_key, 0.0))
    executions = payload.get("execution_ledger", {}).get(order_key, {})
    if processed <= 0 or not executions:
        raise ValueError("confirmed execution evidence was not found")

    total_qty = 0.0
    total_value = 0.0
    for value in executions.values():
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("invalid execution evidence")
        qty, price = float(value[0]), float(value[1])
        if qty <= 0 or price <= 0:
            raise ValueError("invalid execution quantity/price")
        total_qty += qty
        total_value += qty * price

    if abs(total_qty - processed) > 1e-9:
        raise ValueError("execution ledger and processed fill disagree")

    return record_confirmed_fill(
        ticker=ticker,
        side=side,
        filled_quantity=processed,
        avg_fill_price=total_value / total_qty,
        currency=currency,
        order_intent_id=order_intent_id,
        order_log_path=order_log_path,
    )
