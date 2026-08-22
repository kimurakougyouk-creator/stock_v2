from dataclasses import replace

import pytest

from ai_asset_platform.brokers.ibkr_crypto_contract import (
    VerifiedCryptoContractSpec,
    build_verified_crypto_contract,
    verified_crypto_spec_from_candidate,
)
from ai_asset_platform.brokers.ibkr_crypto_discovery import IbkrCryptoCandidate


def _spec() -> VerifiedCryptoContractSpec:
    return VerifiedCryptoContractSpec(
        symbol="BTC",
        exchange="PAXOS",
        currency="USD",
        con_id=479624278,
        local_symbol="BTC.USD",
    )


def test_build_verified_crypto_contract_uses_explicit_fields_only():
    contract = build_verified_crypto_contract(_spec())
    assert contract.secType == "CRYPTO"
    assert contract.symbol == "BTC"
    assert contract.exchange == "PAXOS"
    assert contract.currency == "USD"
    assert contract.conId == 479624278


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", ""),
        ("exchange", "SMART"),
        ("exchange", ""),
        ("currency", "JPY"),
        ("currency", ""),
        ("con_id", 0),
    ],
)
def test_build_verified_crypto_contract_fails_closed(field, value):
    with pytest.raises(ValueError):
        build_verified_crypto_contract(replace(_spec(), **{field: value}))


def test_verified_crypto_spec_from_candidate_preserves_broker_identity():
    candidate = IbkrCryptoCandidate(
        symbol="BTC",
        exchange="ZEROHASH",
        currency="USD",
        local_symbol="BTC.USD",
        con_id=541686651,
        min_tick=0.01,
        valid_exchanges="ZEROHASH",
        order_types="LMT",
        time_zone_id="UTC",
        trading_hours="",
        liquid_hours="",
    )
    spec = verified_crypto_spec_from_candidate(candidate)
    assert spec.symbol == "BTC"
    assert spec.exchange == "ZEROHASH"
    assert spec.currency == "USD"
    assert spec.con_id == 541686651


@pytest.mark.parametrize(
    "exchange,currency",
    [
        ("SMART", "USD"),
        ("PAXOS", "JPY"),
    ],
)
def test_verified_crypto_spec_from_candidate_rejects_unsupported_route(exchange, currency):
    candidate = IbkrCryptoCandidate(
        symbol="BTC",
        exchange=exchange,
        currency=currency,
        local_symbol=None,
        con_id=None,
        min_tick=None,
        valid_exchanges=None,
        order_types=None,
        time_zone_id=None,
        trading_hours=None,
        liquid_hours=None,
    )
    with pytest.raises(ValueError):
        verified_crypto_spec_from_candidate(candidate)
