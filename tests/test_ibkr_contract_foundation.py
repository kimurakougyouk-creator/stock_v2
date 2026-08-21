import pytest

from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract_spec
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


def test_stock_contract_preserves_existing_defaults():
    spec = build_ibkr_contract_spec(InstrumentSpec("AAPL", AssetClass.STOCK))
    assert spec.symbol == "AAPL"
    assert spec.sec_type == "STK"
    assert spec.exchange == "SMART"
    assert spec.currency == "USD"


def test_etf_uses_ibkr_stock_security_type():
    spec = build_ibkr_contract_spec(InstrumentSpec("SPY", AssetClass.ETF))
    assert spec.symbol == "SPY"
    assert spec.sec_type == "STK"
    assert spec.exchange == "SMART"
    assert spec.currency == "USD"


@pytest.mark.parametrize(
    "asset_class",
    [AssetClass.FX, AssetClass.CRYPTO],
)
def test_unverified_simple_asset_classes_fail_closed(asset_class):
    with pytest.raises(ValueError, match="not verified"):
        build_ibkr_contract_spec(InstrumentSpec("TEST", asset_class))


def test_future_requires_expiry_before_broker_mapping():
    with pytest.raises(ValueError, match="expiry"):
        InstrumentSpec("ES", AssetClass.FUTURE)


def test_option_requires_expiry_strike_and_right():
    with pytest.raises(ValueError, match="expiry"):
        InstrumentSpec("AAPL", AssetClass.OPTION)
    with pytest.raises(ValueError, match="strike"):
        InstrumentSpec("AAPL", AssetClass.OPTION, expiry="20261218")
    with pytest.raises(ValueError, match="right"):
        InstrumentSpec(
            "AAPL",
            AssetClass.OPTION,
            expiry="20261218",
            strike=300.0,
            right="X",
        )


def test_future_and_valid_option_still_fail_closed_until_verified():
    future = InstrumentSpec("ES", AssetClass.FUTURE, expiry="202612")
    option = InstrumentSpec(
        "AAPL",
        AssetClass.OPTION,
        expiry="20261218",
        strike=300.0,
        right="C",
        multiplier="100",
    )
    for instrument in (future, option):
        with pytest.raises(ValueError, match="not verified"):
            build_ibkr_contract_spec(instrument)


def test_blank_identity_fields_are_rejected():
    with pytest.raises(ValueError, match="symbol"):
        InstrumentSpec(" ", AssetClass.STOCK)
    with pytest.raises(ValueError, match="exchange"):
        InstrumentSpec("AAPL", AssetClass.STOCK, exchange=" ")
    with pytest.raises(ValueError, match="currency"):
        InstrumentSpec("AAPL", AssetClass.STOCK, currency=" ")
