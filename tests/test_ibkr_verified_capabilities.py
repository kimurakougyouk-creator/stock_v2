import pytest

from ai_asset_platform.brokers.ibkr_verified_capabilities import (
    blocked_option_capability_names,
    require_verified_option_capability,
    verified_option_capability_names,
)


def test_only_directly_proven_option_capabilities_are_verified():
    verified = verified_option_capability_names()
    assert "buy_sell_roundtrip" in verified
    assert "multiplier_realized_pnl" in verified
    assert "restart_execution_recovery" in verified
    assert "exercise" not in verified
    assert "assignment" not in verified
    assert "expiration_settlement" not in verified
    assert "short_option" not in verified
    assert "multi_leg_option" not in verified


def test_unproven_option_lifecycle_capabilities_remain_explicitly_blocked():
    blocked = blocked_option_capability_names()
    assert {"exercise", "assignment", "expiration_settlement", "short_option", "multi_leg_option"} <= blocked
    for name in blocked:
        with pytest.raises(ValueError, match="not verified"):
            require_verified_option_capability(name)


def test_unknown_option_capability_fails_closed():
    with pytest.raises(ValueError, match="unknown"):
        require_verified_option_capability("magic_option_behavior")
