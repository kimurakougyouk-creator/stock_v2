"""Fail-closed IBKR option contract foundation.

Builds an OPT Contract only from explicit, broker-derived fields. This module
never chooses an expiry/strike/right, never assigns a Paper quantity, and never
creates or transmits an Order.
"""
from __future__ import annotations

from dataclasses import dataclass

from ibapi.contract import Contract

from ai_asset_platform.brokers.ibkr_option_discovery import IbkrOptionCandidate


@dataclass(frozen=True)
class VerifiedOptionContractSpec:
    symbol: str
    exchange: str
    currency: str
    expiry: str
    strike: float
    right: str
    multiplier: str
    con_id: int | None = None
    local_symbol: str | None = None
    trading_class: str | None = None


def build_verified_option_contract(spec: VerifiedOptionContractSpec) -> Contract:
    symbol = str(spec.symbol).strip().upper()
    exchange = str(spec.exchange).strip().upper()
    currency = str(spec.currency).strip().upper()
    expiry = str(spec.expiry).strip()
    right = str(spec.right).strip().upper()
    multiplier = str(spec.multiplier).strip()
    strike = float(spec.strike)

    if not symbol:
        raise ValueError("option symbol is required")
    if not exchange:
        raise ValueError("option exchange is required")
    if not currency:
        raise ValueError("option currency is required")
    if not expiry:
        raise ValueError("option expiry is required")
    if strike <= 0:
        raise ValueError("option strike must be positive")
    if right not in {"C", "P"}:
        raise ValueError("option right must be C or P")
    if not multiplier:
        raise ValueError("option multiplier is required")

    contract = Contract()
    contract.symbol = symbol
    contract.secType = "OPT"
    contract.exchange = exchange
    contract.currency = currency
    contract.lastTradeDateOrContractMonth = expiry
    contract.strike = strike
    contract.right = right
    contract.multiplier = multiplier
    if spec.con_id is not None:
        if int(spec.con_id) <= 0:
            raise ValueError("option con_id must be positive when provided")
        contract.conId = int(spec.con_id)
    if spec.local_symbol:
        contract.localSymbol = str(spec.local_symbol).strip()
    if spec.trading_class:
        contract.tradingClass = str(spec.trading_class).strip()
    return contract


def verified_option_spec_from_candidate(candidate: IbkrOptionCandidate) -> VerifiedOptionContractSpec:
    if not candidate.expiry:
        raise ValueError("broker option candidate is missing expiry")
    if candidate.strike is None or float(candidate.strike) <= 0:
        raise ValueError("broker option candidate is missing strike")
    if not candidate.right:
        raise ValueError("broker option candidate is missing right")
    if not candidate.multiplier:
        raise ValueError("broker option candidate is missing multiplier")
    return VerifiedOptionContractSpec(
        symbol=candidate.symbol,
        exchange=candidate.exchange,
        currency=candidate.currency,
        expiry=candidate.expiry,
        strike=float(candidate.strike),
        right=candidate.right,
        multiplier=candidate.multiplier,
        con_id=candidate.con_id,
        local_symbol=candidate.local_symbol,
        trading_class=candidate.trading_class,
    )
