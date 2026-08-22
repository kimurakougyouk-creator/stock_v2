import pytest

from ai_asset_platform.core.asset_classes import (
    AssetClass,
    MarketCapability,
    TARGET_ASSET_CLASSES,
    is_verified_paper_capability,
)


def test_target_scope_includes_all_planned_asset_classes():
    assert set(TARGET_ASSET_CLASSES) == {
        AssetClass.STOCK,
        AssetClass.ETF,
        AssetClass.FX,
        AssetClass.FUTURE,
        AssetClass.OPTION,
        AssetClass.CRYPTO,
    }


def test_verified_ibkr_us_stock_paper_capability():
    assert is_verified_paper_capability(
        market="US_STOCK",
        asset_class=AssetClass.STOCK,
        broker="IBKR",
    )


def test_verified_ibkr_us_etf_paper_capability():
    assert is_verified_paper_capability(
        market="US_ETF",
        asset_class=AssetClass.ETF,
        broker="IBKR",
    )


def test_overnight_is_not_promoted_by_regular_us_etf_verification():
    assert not is_verified_paper_capability(
        market="US_OVERNIGHT",
        asset_class=AssetClass.ETF,
        broker="IBKR",
    )


def test_target_does_not_mean_verified():
    assert not is_verified_paper_capability(
        market="GLOBAL_CRYPTO",
        asset_class=AssetClass.CRYPTO,
        broker="IBKR",
    )


def test_live_cannot_be_enabled_before_paper_verification():
    with pytest.raises(ValueError, match="Live対応はPaper対応"):
        MarketCapability(
            market="TEST",
            asset_class=AssetClass.FUTURE,
            broker="TEST_BROKER",
            paper_supported=False,
            live_supported=True,
        )


def test_capability_requires_market_and_broker():
    with pytest.raises(ValueError, match="marketは空"):
        MarketCapability("", AssetClass.STOCK, "IBKR")
    with pytest.raises(ValueError, match="brokerは空"):
        MarketCapability("US_STOCK", AssetClass.STOCK, "")
