import pytest

from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


def test_us_stock_contract_matches_existing_defaults():
    contract = build_ibkr_contract(
        InstrumentSpec("AAPL", AssetClass.STOCK, "SMART", "USD")
    )
    assert contract.symbol == "AAPL"
    assert contract.secType == "STK"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"


def test_etf_contract_uses_ibkr_stock_security_type():
    contract = build_ibkr_contract(
        InstrumentSpec("SPY", AssetClass.ETF, "SMART", "USD")
    )
    assert contract.symbol == "SPY"
    assert contract.secType == "STK"


def test_fx_contract_is_cash():
    contract = build_ibkr_contract(
        InstrumentSpec("EUR", AssetClass.FX, "IDEALPRO", "USD")
    )
    assert contract.secType == "CASH"


def test_future_requires_expiry_and_maps_to_fut():
    with pytest.raises(ValueError):
        InstrumentSpec("ES", AssetClass.FUTURE, "CME", "USD")

    contract = build_ibkr_contract(
        InstrumentSpec("ES", AssetClass.FUTURE, "CME", "USD", expiry="202612")
    )
    assert contract.secType == "FUT"
    assert contract.lastTradeDateOrContractMonth == "202612"


def test_option_requires_expiry_strike_and_right():
    with pytest.raises(ValueError):
        InstrumentSpec("AAPL", AssetClass.OPTION, "SMART", "USD")

    contract = build_ibkr_contract(
        InstrumentSpec(
            "AAPL",
            AssetClass.OPTION,
            "SMART",
            "USD",
            expiry="20261218",
            strike=300.0,
            right="C",
            multiplier="100",
        )
    )
    assert contract.secType == "OPT"
    assert contract.right == "C"
    assert contract.strike == 300.0
    assert contract.multiplier == "100"


def test_crypto_fails_closed_until_verified():
    with pytest.raises(NotImplementedError):
        build_ibkr_contract(
            InstrumentSpec("BTC", AssetClass.CRYPTO, "PAXOS", "USD")
        )


def test_non_derivative_rejects_derivative_fields():
    with pytest.raises(ValueError):
        InstrumentSpec(
            "SPY",
            AssetClass.ETF,
            "SMART",
            "USD",
            expiry="202612",
        )
