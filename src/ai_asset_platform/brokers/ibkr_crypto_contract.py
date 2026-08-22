"""Fail-closed IBKR cryptocurrency contract foundation.

Builds a CRYPTO Contract only from explicit, broker-derived fields. This module
never selects a token, never chooses an exchange on behalf of the caller, never
assigns a Paper quantity, and never creates or transmits an Order.

IBKR documentation currently describes CRYPTO contracts as explicit
symbol/exchange/currency tuples. Account, residence and venue permissions remain
separate gates and are deliberately not inferred here.
"""
from __future__ import annotations

from dataclasses import dataclass

from ibapi.contract import Contract

from ai_asset_platform.brokers.ibkr_crypto_discovery import IbkrCryptoCandidate


ALLOWED_CRYPTO_EXCHANGES = frozenset({"PAXOS", "ZEROHASH"})


@dataclass(frozen=True)
class VerifiedCryptoContractSpec:
    symbol: str
    exchange: str
    currency: str
    con_id: int | None = None
    local_symbol: str | None = None


def build_verified_crypto_contract(spec: VerifiedCryptoContractSpec) -> Contract:
    symbol = str(spec.symbol).strip().upper()
    exchange = str(spec.exchange).strip().upper()
    currency = str(spec.currency).strip().upper()

    if not symbol:
        raise ValueError("crypto symbol is required")
    if exchange not in ALLOWED_CRYPTO_EXCHANGES:
        raise ValueError("crypto exchange must be explicitly PAXOS or ZEROHASH")
    if currency != "USD":
        raise ValueError("crypto currency must be USD for the currently documented IBKR route")

    contract = Contract()
    contract.symbol = symbol
    contract.secType = "CRYPTO"
    contract.exchange = exchange
    contract.currency = currency
    if spec.con_id is not None:
        if int(spec.con_id) <= 0:
            raise ValueError("crypto con_id must be positive when provided")
        contract.conId = int(spec.con_id)
    if spec.local_symbol:
        contract.localSymbol = str(spec.local_symbol).strip()
    return contract


def verified_crypto_spec_from_candidate(candidate: IbkrCryptoCandidate) -> VerifiedCryptoContractSpec:
    """Convert one broker-returned discovery candidate into an explicit spec.

    This conversion does not prove that the current account or residence may
    trade crypto. It only preserves the broker-returned contract identity.
    """
    if not candidate.symbol:
        raise ValueError("broker crypto candidate is missing symbol")
    exchange = str(candidate.exchange).strip().upper()
    if exchange not in ALLOWED_CRYPTO_EXCHANGES:
        raise ValueError("broker crypto candidate has an unsupported exchange")
    if str(candidate.currency).strip().upper() != "USD":
        raise ValueError("broker crypto candidate has unsupported currency")
    return VerifiedCryptoContractSpec(
        symbol=candidate.symbol,
        exchange=exchange,
        currency="USD",
        con_id=candidate.con_id,
        local_symbol=candidate.local_symbol,
    )
