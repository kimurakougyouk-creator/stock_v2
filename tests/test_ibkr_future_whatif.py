import pytest

from ai_asset_platform.brokers.ibkr_future_whatif import (
    _positive_integral_quantity,
    _positive_price,
)


@pytest.mark.parametrize("value", [1, "1", 2.0])
def test_positive_integral_quantity_accepts_whole_positive_values(value):
    assert _positive_integral_quantity(value) == int(value)


@pytest.mark.parametrize("value", [0, -1, 1.5, "2.25"])
def test_positive_integral_quantity_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="positive integer"):
        _positive_integral_quantity(value)


@pytest.mark.parametrize("value", [0, -0.25, "-1"])
def test_positive_price_rejects_non_positive_values(value):
    with pytest.raises(ValueError, match="positive"):
        _positive_price(value)


def test_positive_price_accepts_fractional_tick_values():
    assert _positive_price("6500.25") == 6500.25
