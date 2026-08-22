"""Fail-closed futures contract foundation for IBKR.

This module only builds explicit FUT contract fields from broker-verified inputs.
It does not enable futures trading, choose a contract month, assign a Paper
quantity, create an Order, or transmit anything.
"""
from __future__ import annotations

from dataclasses import dataclass

from ibapi.contract import Contract


@dataclass(frozen=True)
class VerifiedFutureContractInput:
    symbol: str
    exchange: str
    currency: str
    expiry: str
    multiplier: str
    local_symbol: str | None = None
    con_id: int | None = None


def _required(value: str, name: str) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def build_verified_future_contract(spec: VerifiedFutureContractInput) -> Contract:
    """Build a FUT Contract only when all product-critical fields are explicit."""
    symbol = _required(spec.symbol, "future symbol")
    exchange = _required(spec.exchange, "future exchange")
    currency = _required(spec.currency, "future currency")
    expiry = str(spec.expiry).strip()
    multiplier = str(spec.multiplier).strip()
    if not expiry:
        raise ValueError("future expiry is required")
    if not multiplier:
        raise ValueError("future multiplier is required")
    if spec.con_id is not None and int(spec.con_id) <= 0:
        raise ValueError("future con_id must be positive when provided")

    contract = Contract()
    contract.symbol = symbol
    contract.secType = "FUT"
    contract.exchange = exchange
    contract.currency = currency
    contract.lastTradeDateOrContractMonth = expiry
    contract.multiplier = multiplier
    if spec.local_symbol:
        contract.localSymbol = str(spec.local_symbol).strip()
    if spec.con_id is not None:
        contract.conId = int(spec.con_id)
    return contract


def contract_input_from_discovery_candidate(candidate) -> VerifiedFutureContractInput:
    """Convert one broker discovery candidate without inventing missing fields."""
    expiry = getattr(candidate, "expiry", None)
    multiplier = getattr(candidate, "multiplier", None)
    if not expiry:
        raise ValueError("broker future candidate is missing expiry")
    if not multiplier:
        raise ValueError("broker future candidate is missing multiplier")
    return VerifiedFutureContractInput(
        symbol=getattr(candidate, "symbol", ""),
        exchange=getattr(candidate, "exchange", ""),
        currency=getattr(candidate, "currency", ""),
        expiry=str(expiry),
        multiplier=str(multiplier),
        local_symbol=getattr(candidate, "local_symbol", None),
        con_id=getattr(candidate, "con_id", None),
    )
