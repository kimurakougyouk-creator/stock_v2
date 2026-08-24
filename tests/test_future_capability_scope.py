import pytest

from ai_asset_platform.core.future_capability_scope import (
    ESU6_LONG_ROUNDTRIP_PAPER_SCOPE,
    validate_esu6_long_roundtrip_scope,
)


def test_verified_esu6_scope_is_explicitly_narrow():
    scope = ESU6_LONG_ROUNDTRIP_PAPER_SCOPE
    assert scope.local_symbol == "ESU6"
    assert scope.con_id == 649180671
    assert scope.long_only is True
    assert scope.quantity == 1
    assert scope.start_flat_required is True
    assert scope.end_flat_required is True
    assert scope.overnight_holding_supported is False
    assert scope.expiry_or_roll_supported is False
    assert scope.live_supported is False


def test_observed_esu6_roundtrip_is_inside_scope():
    assert validate_esu6_long_roundtrip_scope(
        local_symbol="ESU6",
        con_id=649180671,
        open_side="BUY",
        close_side="SELL",
        quantity=1,
        start_quantity=0,
        end_quantity=0,
    ) is True


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"local_symbol": "ESZ6"}, "pinned to ESU6"),
        ({"con_id": 1}, "pinned to ESU6"),
        ({"open_side": "SELL", "close_side": "BUY"}, "long-only"),
        ({"quantity": 2}, "exactly one contract"),
        ({"start_quantity": 1}, "start and end flat"),
        ({"end_quantity": 1}, "start and end flat"),
    ],
)
def test_scope_fails_closed_outside_verified_boundary(kwargs, message):
    values = dict(
        local_symbol="ESU6",
        con_id=649180671,
        open_side="BUY",
        close_side="SELL",
        quantity=1,
        start_quantity=0,
        end_quantity=0,
    )
    values.update(kwargs)
    with pytest.raises(ValueError, match=message):
        validate_esu6_long_roundtrip_scope(**values)
