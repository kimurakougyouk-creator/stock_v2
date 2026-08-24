"""Fail-closed FX Contract foundation for IBKR.

This module only builds explicit CASH contract fields from broker-verified
inputs. It does not choose a pair, assign quantity, create an Order, or transmit
anything.
"""
from __future__ import annotations

from dataclasses import dataclass

from ibapi.contract import Contract


@dataclass(frozen=True)
class VerifiedFxContractInput:
    base_currency: str
    quote_currency: str
    exchange: str
    local_symbol: str | None = None
    con_id: int | None = None


def _currency(value: str, name: str) -> str:
    normalized = str(value).strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError(f"{name} must be a 3-letter currency code")
    return normalized


def build_verified_fx_contract(spec: VerifiedFxContractInput) -> Contract:
    base = _currency(spec.base_currency, "FX base currency")
    quote = _currency(spec.quote_currency, "FX quote currency")
    exchange = str(spec.exchange).strip().upper()
    if not exchange:
        raise ValueError("FX exchange is required")
    if base == quote:
        raise ValueError("FX base and quote currencies must differ")
    if spec.con_id is not None and int(spec.con_id) <= 0:
        raise ValueError("FX con_id must be positive when provided")

    contract = Contract()
    contract.symbol = base
    contract.secType = "CASH"
    contract.currency = quote
    contract.exchange = exchange
    if spec.local_symbol:
        contract.localSymbol = str(spec.local_symbol).strip()
    if spec.con_id is not None:
        contract.conId = int(spec.con_id)
    return contract


def contract_input_from_discovery_candidate(candidate) -> VerifiedFxContractInput:
    """Convert one broker FX candidate without inventing missing identity fields."""
    con_id = getattr(candidate, "con_id", None)
    if con_id is None or int(con_id) <= 0:
        raise ValueError("broker FX candidate is missing positive con_id")
    return VerifiedFxContractInput(
        base_currency=getattr(candidate, "base_currency", ""),
        quote_currency=getattr(candidate, "quote_currency", ""),
        exchange=getattr(candidate, "exchange", ""),
        local_symbol=getattr(candidate, "local_symbol", None),
        con_id=int(con_id),
    )
