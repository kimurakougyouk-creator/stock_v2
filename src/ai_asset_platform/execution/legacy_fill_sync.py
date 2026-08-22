"""Synchronize confirmed broker fills into the durable paper-order state.

This module never sends an order. It records only terminal, confirmed fills so
risk/accounting helpers keep reading the same durable state during the IBKR Paper
migration. Optional broker execution identity is preserved for cross-process
idempotency and later reconciliation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ai_asset_platform.core.account_clock import account_now


def _normalized_exec_ids(values: Iterable[object] | None) -> list[str]:
    if values is None:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        exec_id = str(value or "").strip()
        if not exec_id or exec_id in seen:
            continue
        seen.add(exec_id)
        result.append(exec_id)
    return result


def record_confirmed_fill(
    *,
    ticker: str,
    side: str,
    filled_quantity: float,
    avg_fill_price: float,
    currency: str,
    order_intent_id: str,
    order_log_path: Path,
    fx_to_account_rate: float | None = None,
    broker_exec_ids: Iterable[object] | None = None,
    broker_order_id: int | None = None,
) -> dict[str, Any]:
    normalized_side = str(side).upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if not order_intent_id:
        raise ValueError("order_intent_id is required")

    normalized_currency = str(currency).strip().upper()
    if len(normalized_currency) != 3 or not normalized_currency.isalpha():
        raise ValueError("currency must be a 3-letter code")

    quantity = float(filled_quantity)
    price = float(avg_fill_price)
    if quantity <= 0:
        raise ValueError("filled_quantity must be positive")
    if not quantity.is_integer():
        raise ValueError("legacy state requires whole-share fills")
    if price <= 0:
        raise ValueError("avg_fill_price must be positive")

    normalized_fx: float | None = None
    if fx_to_account_rate is not None:
        normalized_fx = float(fx_to_account_rate)
        if normalized_fx <= 0:
            raise ValueError("fx_to_account_rate must be positive when provided")

    exec_ids = _normalized_exec_ids(broker_exec_ids)
    normalized_order_id: int | None = None
    if broker_order_id is not None:
        normalized_order_id = int(broker_order_id)
        if normalized_order_id <= 0:
            raise ValueError("broker_order_id must be positive when provided")

    if order_log_path.exists():
        with order_log_path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if existing.get("order_intent_id") == order_intent_id:
                    return existing

    record: dict[str, Any] = {
        "created_at": account_now().isoformat(timespec="seconds"),
        "mode": "IBKR_PAPER",
        "ticker": str(ticker),
        "side": normalized_side,
        "shares": int(quantity),
        "reference_price": price,
        "currency": normalized_currency,
        "status": "FILLED",
        "order_intent_id": order_intent_id,
    }
    if normalized_fx is not None:
        record["fx_to_account_rate"] = normalized_fx
    if exec_ids:
        record["broker_exec_ids"] = exec_ids
    if normalized_order_id is not None:
        record["broker_order_id"] = normalized_order_id

    order_log_path.parent.mkdir(parents=True, exist_ok=True)
    with order_log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record
