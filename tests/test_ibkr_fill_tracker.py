import pytest

from ai_asset_platform.brokers.ibkr_fill_tracker import IbkrFillTracker
from ai_asset_platform.brokers.ibkr_order_events import (
    create_ibkr_order_status_event,
)


def _event(order_id: int, filled: float, remaining: float):
    return create_ibkr_order_status_event(
        order_id=order_id,
        status="Filled" if remaining == 0 else "Submitted",
        filled=filled,
        remaining=remaining,
        average_fill_price=200.0 if filled > 0 else 0.0,
    )


def test_first_fill_returns_full_delta():
    tracker = IbkrFillTracker()

    assert tracker.get_fill_delta(_event(100, 1, 2)) == 1
    assert tracker.processed_filled(100) == 1


def test_cumulative_partial_fills_return_only_new_quantity():
    tracker = IbkrFillTracker()

    assert tracker.get_fill_delta(_event(100, 1, 2)) == 1
    assert tracker.get_fill_delta(_event(100, 2, 1)) == 1
    assert tracker.get_fill_delta(_event(100, 3, 0)) == 1

    assert tracker.processed_filled(100) == 3


def test_duplicate_event_returns_zero():
    tracker = IbkrFillTracker()

    tracker.get_fill_delta(_event(100, 1, 1))

    assert tracker.get_fill_delta(_event(100, 1, 1)) == 0
    assert tracker.processed_filled(100) == 1


def test_orders_are_tracked_independently():
    tracker = IbkrFillTracker()

    assert tracker.get_fill_delta(_event(100, 1, 0)) == 1
    assert tracker.get_fill_delta(_event(200, 2, 0)) == 2

    assert tracker.processed_filled(100) == 1
    assert tracker.processed_filled(200) == 2


def test_decreasing_cumulative_fill_is_rejected():
    tracker = IbkrFillTracker()

    tracker.get_fill_delta(_event(100, 2, 1))

    with pytest.raises(ValueError):
        tracker.get_fill_delta(_event(100, 1, 2))


def test_clear_removes_completed_order_state():
    tracker = IbkrFillTracker()

    tracker.get_fill_delta(_event(100, 1, 0))
    tracker.clear(100)

    assert tracker.processed_filled(100) == 0
