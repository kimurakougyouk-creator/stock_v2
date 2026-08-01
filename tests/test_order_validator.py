import pytest

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.execution.order_validator import validate_order_request


def test_validate_buy_order():
    order = OrderRequest(
        symbol="7203.T",
        side=OrderSide.BUY,
        quantity=100,
    )

    assert validate_order_request(order) is True


def test_order_request_rejects_invalid_quantity():
    with pytest.raises(ValueError):
        OrderRequest(
            symbol="7203.T",
            side=OrderSide.BUY,
            quantity=0,
        )


def test_order_request_rejects_empty_symbol():
    with pytest.raises(ValueError):
        OrderRequest(
            symbol="",
            side=OrderSide.BUY,
            quantity=100,
        )
