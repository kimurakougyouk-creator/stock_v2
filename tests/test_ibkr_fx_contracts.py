from types import SimpleNamespace

import pytest

from ai_asset_platform.brokers.ibkr_fx_contracts import (
    VerifiedFxContractInput,
    build_verified_fx_contract,
    contract_input_from_discovery_candidate,
)


def test_build_verified_fx_contract_sets_explicit_cash_fields():
    spec = VerifiedFxContractInput(
        base_currency="usd", quote_currency="jpy", exchange="idealpro",
        local_symbol="USD.JPY", con_id=123,
    )
    contract = build_verified_fx_contract(spec)
    assert contract.symbol == "USD"
    assert contract.secType == "CASH"
    assert contract.currency == "JPY"
    assert contract.exchange == "IDEALPRO"
    assert contract.localSymbol == "USD.JPY"
    assert contract.conId == 123


def test_invalid_currency_and_same_pair_fail_closed():
    with pytest.raises(ValueError, match="3-letter"):
        build_verified_fx_contract(
            VerifiedFxContractInput(base_currency="US", quote_currency="JPY", exchange="IDEALPRO")
        )
    with pytest.raises(ValueError, match="must differ"):
        build_verified_fx_contract(
            VerifiedFxContractInput(base_currency="USD", quote_currency="USD", exchange="IDEALPRO")
        )


def test_missing_exchange_and_invalid_con_id_fail_closed():
    with pytest.raises(ValueError, match="exchange"):
        build_verified_fx_contract(
            VerifiedFxContractInput(base_currency="USD", quote_currency="JPY", exchange="")
        )
    with pytest.raises(ValueError, match="con_id"):
        build_verified_fx_contract(
            VerifiedFxContractInput(base_currency="USD", quote_currency="JPY", exchange="IDEALPRO", con_id=0)
        )


def test_candidate_conversion_requires_broker_con_id():
    candidate = SimpleNamespace(
        base_currency="USD", quote_currency="JPY", exchange="IDEALPRO",
        local_symbol="USD.JPY", con_id=123,
    )
    converted = contract_input_from_discovery_candidate(candidate)
    assert converted.base_currency == "USD"
    assert converted.quote_currency == "JPY"
    assert converted.con_id == 123

    with pytest.raises(ValueError, match="con_id"):
        contract_input_from_discovery_candidate(SimpleNamespace(
            base_currency="USD", quote_currency="JPY", exchange="IDEALPRO",
            local_symbol=None, con_id=None,
        ))


def test_foundation_has_no_quantity_or_order_surface():
    fields = VerifiedFxContractInput.__dataclass_fields__
    assert "quantity" not in fields
    assert "verified_paper_test_quantity" not in fields
