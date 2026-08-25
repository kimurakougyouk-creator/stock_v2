import pytest

from ai_asset_platform.core.asset_classes import AssetClass, is_verified_paper_capability
from ai_asset_platform.core.multi_asset_verification import (
    MULTI_ASSET_VERIFICATION,
    VerificationLevel,
    evidence_for,
    validate_verification_matrix,
)


def test_matrix_invariants_are_clean():
    assert validate_verification_matrix() == ()


def test_exact_promoted_issue56_scopes_match_verified_capabilities():
    promoted = [item for item in MULTI_ASSET_VERIFICATION if item.capability_promoted]
    assert [item.key for item in promoted] == ["US_ETF", "FUTURES", "OPTIONS"]
    assert all(item.level is VerificationLevel.VERIFIED_MARKET_PAPER for item in promoted)
    assert all(item.real_paper_e2e is True for item in promoted)
    assert all(item.live_supported is False for item in promoted)
    assert promoted[1].capability_market == "US_ESU6_FUTURE_LONG_ROUNDTRIP"
    assert promoted[2].capability_market == "US_SPY_OPTION_LONG_INTRADAY"


def test_controlled_9432_e2e_does_not_overclaim_global_stock_market_support():
    item = evidence_for("GLOBAL_STOCK_CONTROLLED_9432_TSEJ_JPY")
    assert item.asset_class is AssetClass.STOCK
    assert item.level is VerificationLevel.CONTROLLED_INSTRUMENT_PAPER
    assert item.controlled_instrument == "9432/TSEJ/JPY"
    assert item.real_paper_e2e is True
    assert item.capability_promoted is False
    assert item.paper_market_verified is False


def test_fx_is_read_only_runtime_evidence_not_trading_support():
    item = evidence_for("fx_usd_jpy_idealpro")
    assert item.asset_class is AssetClass.FX
    assert item.level is VerificationLevel.READ_ONLY_RUNTIME
    assert item.contract_foundation is True
    assert item.runtime_contract_evidence is True
    assert item.product_specific_order_path is False
    assert item.trusted_accounting_path is False
    assert item.real_paper_e2e is False
    assert item.capability_promoted is False
    assert any("currency leverage" in gate for gate in item.remaining_gates)


@pytest.mark.parametrize(
    ("key", "asset_class", "capability_market"),
    [
        ("FUTURES", AssetClass.FUTURE, "US_ESU6_FUTURE_LONG_ROUNDTRIP"),
        ("OPTIONS", AssetClass.OPTION, "US_SPY_OPTION_LONG_INTRADAY"),
    ],
)
def test_exact_derivative_scopes_are_promoted_without_generalizing(key, asset_class, capability_market):
    item = evidence_for(key)
    assert item.asset_class is asset_class
    assert item.level is VerificationLevel.VERIFIED_MARKET_PAPER
    assert item.contract_foundation is True
    assert item.runtime_contract_evidence is True
    assert item.product_specific_order_path is True
    assert item.trusted_accounting_path is True
    assert item.real_paper_e2e is True
    assert item.capability_promoted is True
    assert item.capability_market == capability_market
    assert item.live_supported is False
    assert item.remaining_gates


def test_crypto_is_runtime_catalog_evidence_only_and_remains_unpromoted():
    item = evidence_for("CRYPTO")
    assert item.asset_class is AssetClass.CRYPTO
    assert item.level is VerificationLevel.READ_ONLY_RUNTIME
    assert item.contract_foundation is True
    assert item.runtime_contract_evidence is True
    assert item.product_specific_order_path is False
    assert item.trusted_accounting_path is False
    assert item.real_paper_e2e is False
    assert item.capability_promoted is False
    assert item.controlled_instrument == "BTC/USD ContractDetails on PAXOS and ZEROHASH"
    assert item.live_supported is False


def test_unverified_broad_products_are_absent_from_verified_capabilities():
    assert not is_verified_paper_capability(
        market="FX_USD_JPY_IDEALPRO", asset_class=AssetClass.FX, broker="IBKR"
    )
    assert not is_verified_paper_capability(
        market="FUTURES", asset_class=AssetClass.FUTURE, broker="IBKR"
    )
    assert not is_verified_paper_capability(
        market="OPTIONS", asset_class=AssetClass.OPTION, broker="IBKR"
    )
    assert not is_verified_paper_capability(
        market="CRYPTO", asset_class=AssetClass.CRYPTO, broker="IBKR"
    )


def test_exact_derivative_capabilities_are_present():
    assert is_verified_paper_capability(
        market="US_ESU6_FUTURE_LONG_ROUNDTRIP", asset_class=AssetClass.FUTURE, broker="IBKR"
    )
    assert is_verified_paper_capability(
        market="US_SPY_OPTION_LONG_INTRADAY", asset_class=AssetClass.OPTION, broker="IBKR"
    )


def test_unknown_matrix_key_fails_closed():
    with pytest.raises(KeyError, match="unknown multi-asset verification key"):
        evidence_for("UNKNOWN")
