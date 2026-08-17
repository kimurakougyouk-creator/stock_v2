import pytest

from ai_asset_platform.brokers.ibkr_fill_bridge import (
    convert_ibkr_event_to_fill,
)
from ai_asset_platform.brokers.ibkr_order_events import (
    create_ibkr_order_status_event,
)
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide


def _request(quantity=1):
    return OrderRequest(
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=quantity,
    )


def test_no_fill_returns_none():
    event = create_ibkr_order_status_event(
        order_id=100,
        status="Submitted",
        filled=0,
        remaining=1,
        average_fill_price=0,
    )

    assert convert_ibkr_event_to_fill(_request(), event) is None


def test_completed_fill_converts_to_existing_fill_result():
    event = create_ibkr_order_status_event(
        order_id=101,
        status="Filled",
        filled=1,
        remaining=0,
        average_fill_price=205.5,
    )

    fill = convert_ibkr_event_to_fill(_request(), event)

    assert fill is not None
    assert fill.order_id == "101"
    assert fill.symbol == "AAPL"
    assert fill.side is OrderSide.BUY
    assert fill.quantity == 1
    assert fill.fill_price == 205.5


def test_partial_fill_can_be_converted():
    event = create_ibkr_order_status_event(
        order_id=102,
        status="Submitted",
        filled=1,
        remaining=1,
        average_fill_price=200.0,
    )

    fill = convert_ibkr_event_to_fill(_request(quantity=2), event)

    assert fill is not None
    assert fill.quantity == 1
    assert fill.fill_price == 200.0


def test_non_fill_terminal_state_returns_none():
    event = create_ibkr_order_status_event(
        order_id=103,
        status="Cancelled",
        filled=1,
        remaining=0,
        average_fill_price=200.0,
    )

    assert convert_ibkr_event_to_fill(_request(), event) is None


def test_zero_fill_price_is_rejected():
    event = create_ibkr_order_status_event(
        order_id=104,
        status="Filled",
        filled=1,
        remaining=0,
        average_fill_price=0,
    )

    with pytest.raises(ValueError):
        convert_ibkr_event_to_fill(_request(), event)


def test_overfill_is_rejected():
    event = create_ibkr_order_status_event(
        order_id=105,
        status="Filled",
        filled=2,
        remaining=0,
        average_fill_price=200.0,
    )

    with pytest.raises(ValueError):
        convert_ibkr_event_to_fill(_request(quantity=1), event)
