import pytest

from ai_asset_platform.brokers.ibkr_fill_pipeline import IbkrFillPipeline
from ai_asset_platform.brokers.ibkr_order_events import (
    create_ibkr_order_status_event,
)
from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderSide,
    OrderType,
)


def _request(quantity: int = 3) -> OrderRequest:
    return OrderRequest(
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=OrderType.MARKET,
    )


def _event(
    filled: float,
    remaining: float,
    price: float = 200.0,
    order_id: int = 100,
):
    return create_ibkr_order_status_event(
        order_id=order_id,
        status="Filled" if remaining == 0 else "Submitted",
        filled=filled,
        remaining=remaining,
        average_fill_price=price,
    )


def test_first_partial_fill_creates_fill_result():
    pipeline = IbkrFillPipeline()

    fill = pipeline.process(
        _request(3),
        _event(1, 2, 200.0),
    )

    assert fill is not None
    assert fill.order_id == "100"
    assert fill.symbol == "AAPL"
    assert fill.quantity == 1
    assert fill.fill_price == 200.0


def test_cumulative_fills_are_converted_to_deltas():
    pipeline = IbkrFillPipeline()
    request = _request(3)

    first = pipeline.process(
        request,
        _event(1, 2, 200.0),
    )
    second = pipeline.process(
        request,
        _event(2, 1, 201.0),
    )
    third = pipeline.process(
        request,
        _event(3, 0, 202.0),
    )

    assert first is not None
    assert second is not None
    assert third is not None

    assert first.quantity == 1
    assert second.quantity == 1
    assert third.quantity == 1

    assert first.fill_price == 200.0
    assert second.fill_price == 201.0
    assert third.fill_price == 202.0

    assert pipeline.processed_filled(100) == 3


def test_duplicate_event_does_not_create_second_fill():
    pipeline = IbkrFillPipeline()
    request = _request(3)
    event = _event(1, 2)

    first = pipeline.process(request, event)
    duplicate = pipeline.process(request, event)

    assert first is not None
    assert duplicate is None
    assert pipeline.processed_filled(100) == 1


def test_no_fill_returns_none():
    pipeline = IbkrFillPipeline()

    result = pipeline.process(
        _request(3),
        _event(0, 3, 0.0),
    )

    assert result is None
    assert pipeline.processed_filled(100) == 0


def test_overfill_is_rejected():
    pipeline = IbkrFillPipeline()

    with pytest.raises(ValueError):
        pipeline.process(
            _request(3),
            _event(4, 0),
        )


def test_decreasing_cumulative_fill_is_rejected():
    pipeline = IbkrFillPipeline()
    request = _request(3)

    pipeline.process(
        request,
        _event(2, 1),
    )

    with pytest.raises(ValueError):
        pipeline.process(
            request,
            _event(1, 2),
        )


def test_different_orders_are_independent():
    pipeline = IbkrFillPipeline()

    first = pipeline.process(
        _request(1),
        _event(1, 0, order_id=100),
    )
    second = pipeline.process(
        _request(1),
        _event(1, 0, order_id=200),
    )

    assert first is not None
    assert second is not None
    assert first.order_id == "100"
    assert second.order_id == "200"


def test_clear_allows_order_state_to_be_removed():
    pipeline = IbkrFillPipeline()
    request = _request(1)
    event = _event(1, 0)

    first = pipeline.process(request, event)
    pipeline.clear(100)

    assert first is not None
    assert pipeline.processed_filled(100) == 0
