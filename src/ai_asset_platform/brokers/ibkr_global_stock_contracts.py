"""Fail-closed non-US/global stock Contract foundation for IBKR.

This module only builds explicit STK contract fields from broker-verified inputs.
It does not select a market, infer currency, assign a Paper quantity, create an
Order, or transmit anything.
"""
from __future__ import annotations

from dataclasses import dataclass

from ibapi.contract import Contract


@dataclass(frozen=True)
class VerifiedGlobalStockContractInput:
    symbol: str
    exchange: str
    currency: str
    primary_exchange: str | None = None
    local_symbol: str | None = None
    con_id: int | None = None


def _required(value: str, name: str) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def build_verified_global_stock_contract(spec: VerifiedGlobalStockContractInput) -> Contract:
    """Build STK only when the market-critical identity fields are explicit."""
    symbol = _required(spec.symbol, "stock symbol")
    exchange = _required(spec.exchange, "stock exchange")
    currency = _required(spec.currency, "stock currency")
    if spec.con_id is not None and int(spec.con_id) <= 0:
        raise ValueError("stock con_id must be positive when provided")

    contract = Contract()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = exchange
    contract.currency = currency
    if spec.primary_exchange:
        contract.primaryExchange = str(spec.primary_exchange).strip().upper()
    if spec.local_symbol:
        contract.localSymbol = str(spec.local_symbol).strip()
    if spec.con_id is not None:
        contract.conId = int(spec.con_id)
    return contract


def contract_input_from_discovery_candidate(candidate) -> VerifiedGlobalStockContractInput:
    """Convert one broker discovery candidate without inventing missing fields."""
    symbol = getattr(candidate, "symbol", "")
    exchange = getattr(candidate, "exchange", "")
    currency = getattr(candidate, "currency", "")
    con_id = getattr(candidate, "con_id", None)
    if not str(symbol).strip():
        raise ValueError("broker stock candidate is missing symbol")
    if not str(exchange).strip():
        raise ValueError("broker stock candidate is missing exchange")
    if not str(currency).strip():
        raise ValueError("broker stock candidate is missing currency")
    if con_id is None or int(con_id) <= 0:
        raise ValueError("broker stock candidate is missing positive con_id")
    return VerifiedGlobalStockContractInput(
        symbol=str(symbol),
        exchange=str(exchange),
        currency=str(currency),
        primary_exchange=getattr(candidate, "primary_exchange", None),
        local_symbol=getattr(candidate, "local_symbol", None),
        con_id=int(con_id),
    )
