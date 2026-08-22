import pytest

from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


def test_unverified_quantity_defaults_to_none():
    instrument = InstrumentSpec("AAPL", AssetClass.STOCK)
    assert instrument.verified_paper_test_quantity is None


def test_explicit_verified_quantity_is_preserved():
    instrument = InstrumentSpec(
        "SPY",
        AssetClass.ETF,
        verified_paper_test_quantity=1,
    )
    assert instrument.verified_paper_test_quantity == 1


def test_non_positive_verified_quantity_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        InstrumentSpec(
            "9432",
            AssetClass.STOCK,
            exchange="TSEJ",
            currency="JPY",
            verified_paper_test_quantity=0,
        )
