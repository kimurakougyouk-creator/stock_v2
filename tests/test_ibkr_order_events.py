import pytest

from ai_asset_platform.brokers.ibkr_order_events import (
    IbkrOrderState,
    create_ibkr_order_status_event,
    normalize_ibkr_order_state,
)


def test_normalize_known_ibkr_status():
    assert normalize_ibkr_order_state("Submitted") is IbkrOrderState.SUBMITTED
    assert normalize_ibkr_order_state("Filled") is IbkrOrderState.FILLED


def test_unknown_ibkr_status_is_safe():
    assert normalize_ibkr_order_state("SOMETHING_NEW") is IbkrOrderState.UNKNOWN


def test_create_submitted_order_event():
    event = create_ibkr_order_status_event(
        order_id=100,
        status="Submitted",
        filled=0,
        remaining=1,
        average_fill_price=0,
    )

    assert event.order_id == 100
    assert event.status is IbkrOrderState.SUBMITTED
    assert event.has_fill is False
    assert event.is_complete is False


def test_create_partial_fill_event():
    event = create_ibkr_order_status_event(
        order_id=101,
        status="Submitted",
        filled=1,
        remaining=1,
        average_fill_price=200.0,
    )

    assert event.has_fill is True
    assert event.is_complete is False


def test_create_completed_fill_event():
    event = create_ibkr_order_status_event(
        order_id=102,
        status="Filled",
        filled=1,
        remaining=0,
        average_fill_price=205.5,
    )

    assert event.status is IbkrOrderState.FILLED
    assert event.has_fill is True
    assert event.is_complete is True
    assert event.average_fill_price == 205.5


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(order_id=-1, status="Submitted", filled=0, remaining=1, average_fill_price=0),
        dict(order_id=1, status="Submitted", filled=-1, remaining=1, average_fill_price=0),
        dict(order_id=1, status="Submitted", filled=0, remaining=-1, average_fill_price=0),
        dict(order_id=1, status="Submitted", filled=0, remaining=1, average_fill_price=-1),
    ],
)
def test_invalid_order_event_is_rejected(kwargs):
    with pytest.raises(ValueError):
        create_ibkr_order_status_event(**kwargs)
