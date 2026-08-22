from types import SimpleNamespace

import pytest

from ai_asset_platform.brokers.ibkr_future_contracts import (
    VerifiedFutureContractInput,
    build_verified_future_contract,
    contract_input_from_discovery_candidate,
)


def test_build_verified_future_contract_sets_only_explicit_fields():
    spec = VerifiedFutureContractInput(
        symbol="es",
        exchange="cme",
        currency="usd",
        expiry="202612",
        multiplier="50",
        local_symbol="ESZ6",
        con_id=123,
    )

    contract = build_verified_future_contract(spec)

    assert contract.symbol == "ES"
    assert contract.secType == "FUT"
    assert contract.exchange == "CME"
    assert contract.currency == "USD"
    assert contract.lastTradeDateOrContractMonth == "202612"
    assert contract.multiplier == "50"
    assert contract.localSymbol == "ESZ6"
    assert contract.conId == 123


def test_missing_expiry_fails_closed():
    spec = VerifiedFutureContractInput(
        symbol="ES",
        exchange="CME",
        currency="USD",
        expiry="",
        multiplier="50",
    )
    with pytest.raises(ValueError, match="expiry"):
        build_verified_future_contract(spec)


def test_missing_multiplier_fails_closed():
    spec = VerifiedFutureContractInput(
        symbol="ES",
        exchange="CME",
        currency="USD",
        expiry="202612",
        multiplier="",
    )
    with pytest.raises(ValueError, match="multiplier"):
        build_verified_future_contract(spec)


def test_invalid_con_id_fails_closed():
    spec = VerifiedFutureContractInput(
        symbol="ES",
        exchange="CME",
        currency="USD",
        expiry="202612",
        multiplier="50",
        con_id=0,
    )
    with pytest.raises(ValueError, match="con_id"):
        build_verified_future_contract(spec)


def test_candidate_conversion_requires_broker_expiry_and_multiplier():
    candidate = SimpleNamespace(
        symbol="ES",
        exchange="CME",
        currency="USD",
        expiry="202612",
        multiplier="50",
        local_symbol="ESZ6",
        con_id=123,
    )
    converted = contract_input_from_discovery_candidate(candidate)
    assert converted.expiry == "202612"
    assert converted.multiplier == "50"

    with pytest.raises(ValueError, match="expiry"):
        contract_input_from_discovery_candidate(SimpleNamespace(
            symbol="ES", exchange="CME", currency="USD", expiry=None,
            multiplier="50", local_symbol=None, con_id=None,
        ))
