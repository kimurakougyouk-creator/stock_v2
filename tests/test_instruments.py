import pytest

from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


@pytest.mark.parametrize("field,value", [("symbol", ""), ("exchange", ""), ("currency", "")])
def test_required_text_fields_reject_blank(field, value):
    kwargs = {
        "symbol": "AAPL",
        "asset_class": AssetClass.STOCK,
        "exchange": "SMART",
        "currency": "USD",
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        InstrumentSpec(**kwargs)


def test_option_rejects_invalid_right():
    with pytest.raises(ValueError):
        InstrumentSpec(
            "AAPL",
            AssetClass.OPTION,
            "SMART",
            "USD",
            expiry="20261218",
            strike=300.0,
            right="X",
        )
