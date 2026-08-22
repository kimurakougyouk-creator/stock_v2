"""Synchronize confirmed broker fills into the legacy paper-order state.

This module never sends an order. It records only terminal, confirmed fills so
legacy risk/accounting helpers keep reading the same durable state during the
IBKR Paper migration.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


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
) -> dict[str, Any]:
    """Append one confirmed fill, idempotently by ``order_intent_id``.

    Currency is mandatory. An explicit FX conversion rate may be persisted when
    it was independently observed; missing FX never blocks preservation of the
    confirmed broker fill itself. Existing records with the same intent id are
    returned unchanged, preventing duplicate accounting after retries/restarts.
    """
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
        "created_at": datetime.now().isoformat(timespec="seconds"),
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

    order_log_path.parent.mkdir(parents=True, exist_ok=True)
    with order_log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record
