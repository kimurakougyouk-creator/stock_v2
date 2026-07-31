from ai_asset_platform.execution.order_request import OrderRequest
from ai_asset_platform.execution.order_validator import (
    validate_order_request,
)


def test_validate_buy_order():
    order = OrderRequest(
        symbol="7203.T",
        action="BUY",
        quantity=100,
    )

    assert validate_order_request(order) is True


def test_validate_invalid_quantity():
    order = OrderRequest(
        symbol="7203.T",
        action="BUY",
        quantity=0,
    )

    assert validate_order_request(order) is False


def test_validate_invalid_action():
    order = OrderRequest(
        symbol="7203.T",
        action="HOLD",
        quantity=100,
    )

    assert validate_order_request(order) is False
