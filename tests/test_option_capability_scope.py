from datetime import date

import pytest

from ai_asset_platform.core.option_capability_scope import (
    SPY_LONG_INTRADAY_PAPER_SCOPE,
    validate_spy_long_intraday_roundtrip_scope,
)


def test_verified_scope_is_explicitly_narrow_and_live_disabled():
    scope = SPY_LONG_INTRADAY_PAPER_SCOPE
    assert scope.underlying == "SPY"
    assert scope.long_only is True
    assert scope.same_session_close_required is True
    assert scope.hold_through_expiry_allowed is False
    assert scope.exercise_supported is False
    assert scope.assignment_supported is False
    assert scope.live_supported is False


def test_observed_paper_roundtrip_is_inside_scope():
    assert validate_spy_long_intraday_roundtrip_scope(
        underlying="SPY",
        open_side="BUY",
        close_side="SELL",
        start_quantity=0,
        end_quantity=0,
        open_date=date(2026, 8, 24),
        close_date=date(2026, 8, 24),
        expiry="20260828",
    ) is True


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"underlying": "AAPL"}, "pinned to SPY"),
        ({"open_side": "SELL", "close_side": "BUY"}, "long-only"),
        ({"start_quantity": 1}, "start and end flat"),
        ({"end_quantity": 1}, "start and end flat"),
        ({"close_date": date(2026, 8, 25)}, "same-session"),
        ({"open_date": date(2026, 8, 28), "close_date": date(2026, 8, 28)}, "expiry-day"),
    ],
)
def test_scope_fails_closed_outside_verified_boundary(kwargs, message):
    values = dict(
        underlying="SPY",
        open_side="BUY",
        close_side="SELL",
        start_quantity=0,
        end_quantity=0,
        open_date=date(2026, 8, 24),
        close_date=date(2026, 8, 24),
        expiry="20260828",
    )
    values.update(kwargs)
    with pytest.raises(ValueError, match=message):
        validate_spy_long_intraday_roundtrip_scope(**values)
