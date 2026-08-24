from types import SimpleNamespace

import pytest

from ai_asset_platform.brokers.ibkr_global_stock_contracts import (
    VerifiedGlobalStockContractInput,
    build_verified_global_stock_contract,
    contract_input_from_discovery_candidate,
)


def test_build_verified_global_stock_contract_sets_only_explicit_fields():
    spec = VerifiedGlobalStockContractInput(
        symbol="7203",
        exchange="tsej",
        currency="jpy",
        primary_exchange="tsej",
        local_symbol="7203",
        con_id=123,
    )
    contract = build_verified_global_stock_contract(spec)
    assert contract.symbol == "7203"
    assert contract.secType == "STK"
    assert contract.exchange == "TSEJ"
    assert contract.currency == "JPY"
    assert contract.primaryExchange == "TSEJ"
    assert contract.localSymbol == "7203"
    assert contract.conId == 123


def test_missing_market_identity_fails_closed():
    with pytest.raises(ValueError, match="exchange"):
        build_verified_global_stock_contract(
            VerifiedGlobalStockContractInput(symbol="7203", exchange="", currency="JPY")
        )
    with pytest.raises(ValueError, match="currency"):
        build_verified_global_stock_contract(
            VerifiedGlobalStockContractInput(symbol="7203", exchange="TSEJ", currency="")
        )


def test_invalid_con_id_fails_closed():
    with pytest.raises(ValueError, match="con_id"):
        build_verified_global_stock_contract(
            VerifiedGlobalStockContractInput(
                symbol="7203", exchange="TSEJ", currency="JPY", con_id=0
            )
        )


def test_candidate_conversion_requires_broker_identity_and_con_id():
    candidate = SimpleNamespace(
        symbol="7203", exchange="TSEJ", currency="JPY",
        primary_exchange="TSEJ", local_symbol="7203", con_id=123,
    )
    converted = contract_input_from_discovery_candidate(candidate)
    assert converted.symbol == "7203"
    assert converted.exchange == "TSEJ"
    assert converted.currency == "JPY"
    assert converted.con_id == 123

    with pytest.raises(ValueError, match="con_id"):
        contract_input_from_discovery_candidate(SimpleNamespace(
            symbol="7203", exchange="TSEJ", currency="JPY",
            primary_exchange=None, local_symbol=None, con_id=None,
        ))


def test_foundation_has_no_quantity_or_order_surface():
    fields = VerifiedGlobalStockContractInput.__dataclass_fields__
    assert "quantity" not in fields
    assert "verified_paper_test_quantity" not in fields
