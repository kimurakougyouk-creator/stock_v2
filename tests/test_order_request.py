from ai_asset_platform.execution.order_candidate import OrderCandidate
from ai_asset_platform.execution.order_request import (
    OrderRequest,
    create_order_request,
)


def test_create_order_request():
    candidate = OrderCandidate(
        symbol="7203.T",
        action="BUY",
        quantity=100,
    )

    request = create_order_request(candidate)

    assert isinstance(request, OrderRequest)
    assert request.symbol == "7203.T"
    assert request.action == "BUY"
    assert request.quantity == 100


def test_create_order_request_sell():
    candidate = OrderCandidate(
        symbol="6758.T",
        action="SELL",
        quantity=50,
    )

    request = create_order_request(candidate)

    assert request.action == "SELL"
    assert request.quantity == 50
