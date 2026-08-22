"""Fail-closed broker/local position reconciliation for IBKR Paper execution.

The durable local ledger is not allowed to disagree with the actual Paper
account immediately before a new automated order. This module is read-only: it
queries the broker account snapshot and never creates, changes, cancels, or
transmits an order.
"""
from __future__ import annotations

from dataclasses import dataclass

import order_manager

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.core.settings import SETTINGS


@dataclass(frozen=True)
class BrokerPositionGuardResult:
    allowed: bool
    reason: str
    ticker: str
    local_quantity: float | None
    broker_quantity: float | None
    account: IbkrPaperAccountSnapshot | None


def _local_confirmed_quantity(records: list[dict], ticker: str) -> float | None:
    target = str(ticker).strip().upper()
    held = 0.0
    seen: set[str] = set()
    for row in records:
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")).strip().upper() != "FILLED":
            continue
        if str(row.get("ticker", "")).strip().upper() != target:
            continue
        intent = str(row.get("order_intent_id", "")).strip()
        if intent and intent in seen:
            continue
        side = str(row.get("side", "")).strip().upper()
        try:
            qty = float(row.get("shares"))
        except (TypeError, ValueError):
            return None
        if qty <= 0 or side not in {"BUY", "SELL"}:
            return None
        if side == "BUY":
            held += qty
        else:
            if qty > held + 1e-9:
                return None
            held -= qty
        if intent:
            seen.add(intent)
    return held


def _broker_quantity(account: IbkrPaperAccountSnapshot, ticker: str) -> float:
    target = str(ticker).strip().upper()
    return sum(
        float(position.quantity)
        for position in account.positions
        if str(position.symbol).strip().upper() == target
    )


def evaluate_broker_position_guard(
    *,
    ticker: str,
    side: str,
    quantity: int,
    account: IbkrPaperAccountSnapshot | None = None,
    records: list[dict] | None = None,
) -> BrokerPositionGuardResult:
    """Require local confirmed position state to match the actual Paper account."""
    normalized_ticker = str(ticker).strip().upper()
    normalized_side = str(side).strip().upper()
    requested = int(quantity)
    if not normalized_ticker or normalized_side not in {"BUY", "SELL"} or requested <= 0:
        return BrokerPositionGuardResult(False, "invalid order identity for broker position guard", normalized_ticker, None, None, account)

    local_records = list(order_manager.load_accounting_orders() if records is None else records)
    local_qty = _local_confirmed_quantity(local_records, normalized_ticker)
    if local_qty is None:
        return BrokerPositionGuardResult(False, "local confirmed position cannot be reconstructed safely", normalized_ticker, None, None, account)

    broker_account = account if account is not None else preview_ibkr_paper_account_snapshot()
    if not broker_account.ready:
        return BrokerPositionGuardResult(False, "broker Paper account snapshot is not ready", normalized_ticker, local_qty, None, broker_account)
    configured_currency = str(SETTINGS.account_currency).strip().upper()
    if str(broker_account.base_currency).strip().upper() != configured_currency:
        return BrokerPositionGuardResult(False, "broker base currency does not match configured account currency", normalized_ticker, local_qty, None, broker_account)

    broker_qty = _broker_quantity(broker_account, normalized_ticker)
    if abs(float(local_qty) - float(broker_qty)) > 1e-9:
        return BrokerPositionGuardResult(
            False,
            f"broker/local position mismatch: local={local_qty:g}, broker={broker_qty:g}",
            normalized_ticker,
            local_qty,
            broker_qty,
            broker_account,
        )

    if normalized_side == "BUY" and broker_qty > 0:
        return BrokerPositionGuardResult(False, "new BUY blocked because the symbol is already held", normalized_ticker, local_qty, broker_qty, broker_account)
    if normalized_side == "SELL" and broker_qty + 1e-9 < requested:
        return BrokerPositionGuardResult(False, "SELL quantity exceeds reconciled broker holdings", normalized_ticker, local_qty, broker_qty, broker_account)

    return BrokerPositionGuardResult(True, "broker/local positions reconciled", normalized_ticker, local_qty, broker_qty, broker_account)
