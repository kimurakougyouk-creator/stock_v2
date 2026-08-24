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


def test_etf_is_the_only_issue56_target_here_with_market_level_promotion():
    promoted = [item for item in MULTI_ASSET_VERIFICATION if item.capability_promoted]
    assert [item.key for item in promoted] == ["US_ETF"]
    assert promoted[0].level is VerificationLevel.VERIFIED_MARKET_PAPER
    assert promoted[0].real_paper_e2e is True
    assert promoted[0].live_supported is False


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


@pytest.mark.parametrize(
    ("key", "asset_class"),
    [
        ("FUTURES", AssetClass.FUTURE),
        ("OPTIONS", AssetClass.OPTION),
        ("CRYPTO", AssetClass.CRYPTO),
    ],
)
def test_foundation_only_products_remain_unpromoted(key, asset_class):
    item = evidence_for(key)
    assert item.asset_class is asset_class
    assert item.level is VerificationLevel.CONTRACT_FOUNDATION
    assert item.contract_foundation is True
    assert item.runtime_contract_evidence is False
    assert item.product_specific_order_path is False
    assert item.trusted_accounting_path is False
    assert item.real_paper_e2e is False
    assert item.capability_promoted is False
    assert item.live_supported is False


def test_unsupported_issue56_products_are_absent_from_verified_capabilities():
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


def test_unknown_matrix_key_fails_closed():
    with pytest.raises(KeyError, match="unknown multi-asset verification key"):
        evidence_for("UNKNOWN")
