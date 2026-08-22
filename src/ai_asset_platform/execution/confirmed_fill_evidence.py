"""Shared, fail-closed interpretation of direct IBKR fill evidence.

A caller may accept either an explicit Filled orderStatus or complete execDetails
for the same order. Missing/open-order absence alone is never evidence. Duplicate
exec_id callbacks are ignored and partial execution evidence remains unconfirmed.
"""
from __future__ import annotations


def confirmed_fill_from_broker_result(
    result,
    expected_quantity: int,
) -> tuple[float, float] | None:
    if expected_quantity <= 0:
        raise ValueError("expected_quantity must be positive")
    if result is None or not getattr(result, "sent", False):
        return None
    if not getattr(result, "reached_terminal", False):
        return None

    filled_quantity = float(getattr(result, "filled_quantity", 0.0) or 0.0)
    avg_fill_price = getattr(result, "avg_fill_price", None)
    last_status = str(getattr(result, "last_known_status", "") or "")
    if (
        last_status == "Filled"
        and filled_quantity >= expected_quantity
        and avg_fill_price is not None
        and float(avg_fill_price) > 0
    ):
        return filled_quantity, float(avg_fill_price)

    order_id = getattr(result, "order_id", None)
    if order_id is None:
        return None

    executions = getattr(result, "executions", None) or []
    unique: dict[str, tuple[float, float]] = {}
    for execution in executions:
        if not isinstance(execution, dict):
            continue
        try:
            execution_order_id = int(execution.get("order_id", -1))
            expected_order_id = int(order_id)
        except (TypeError, ValueError):
            continue
        if execution_order_id != expected_order_id:
            continue
        exec_id = str(execution.get("exec_id", "")).strip()
        if not exec_id or exec_id in unique:
            continue
        try:
            shares = float(execution.get("shares", 0.0))
            price = float(execution.get("price", 0.0))
        except (TypeError, ValueError):
            continue
        if shares <= 0 or price <= 0:
            continue
        unique[exec_id] = (shares, price)

    execution_quantity = sum(shares for shares, _ in unique.values())
    if execution_quantity < expected_quantity:
        return None
    execution_notional = sum(shares * price for shares, price in unique.values())
    if execution_notional <= 0:
        return None
    return execution_quantity, execution_notional / execution_quantity
