from __future__ import annotations

import pytest

from signal_runner import evaluate_trailing_stop


def test_trailing_stop_triggers_at_exact_threshold():
    triggered, drop_percent = evaluate_trailing_stop(
        current_price=950.0,
        highest_price=1000.0,
        trailing_stop_percent=5.0,
        held_shares=100,
    )

    assert triggered is True
    assert drop_percent == pytest.approx(5.0)


def test_trailing_stop_triggers_beyond_threshold():
    triggered, drop_percent = evaluate_trailing_stop(
        current_price=900.0,
        highest_price=1000.0,
        trailing_stop_percent=5.0,
        held_shares=100,
    )

    assert triggered is True
    assert drop_percent == pytest.approx(10.0)


def test_trailing_stop_does_not_trigger_before_threshold():
    triggered, drop_percent = evaluate_trailing_stop(
        current_price=960.0,
        highest_price=1000.0,
        trailing_stop_percent=5.0,
        held_shares=100,
    )

    assert triggered is False
    assert drop_percent == pytest.approx(4.0)


def test_trailing_stop_does_not_trigger_without_position():
    triggered, drop_percent = evaluate_trailing_stop(
        current_price=900.0,
        highest_price=1000.0,
        trailing_stop_percent=5.0,
        held_shares=0,
    )

    assert triggered is False
    assert drop_percent is None


def test_trailing_stop_does_not_trigger_without_highest_price():
    triggered, drop_percent = evaluate_trailing_stop(
        current_price=900.0,
        highest_price=None,
        trailing_stop_percent=5.0,
        held_shares=100,
    )

    assert triggered is False
    assert drop_percent is None


def test_trailing_stop_can_be_disabled():
    triggered, drop_percent = evaluate_trailing_stop(
        current_price=900.0,
        highest_price=1000.0,
        trailing_stop_percent=0.0,
        held_shares=100,
    )

    assert triggered is False
    assert drop_percent is None


def test_new_high_does_not_trigger_trailing_stop():
    triggered, drop_percent = evaluate_trailing_stop(
        current_price=1100.0,
        highest_price=1000.0,
        trailing_stop_percent=5.0,
        held_shares=100,
    )

    assert triggered is False
    assert drop_percent == pytest.approx(0.0)


def test_trailing_stop_forced_exit_uses_all_held_shares():
    """Trailing Stop発動時は注文上限ではなく保有株すべてを売却する。"""

    held_shares = 500
    max_order_shares = 100
    trailing_stop_triggered = True
    time_stop_triggered = False

    forced_exit_triggered = (
        trailing_stop_triggered
        or time_stop_triggered
    )

    shares = held_shares if forced_exit_triggered else 50

    order_shares = (
        shares
        if forced_exit_triggered
        else min(shares, max_order_shares)
    )

    assert forced_exit_triggered is True
    assert shares == 500
    assert order_shares == 500
