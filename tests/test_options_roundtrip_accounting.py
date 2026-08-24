from decimal import Decimal

import pytest

from ai_asset_platform.accounting.options_roundtrip_accounting import (
    OptionFillEvidence,
    account_closed_option_roundtrip,
    option_recovery_identity,
)


def _fill(**overrides):
    values = dict(
        execution_id="E1",
        con_id=900369377,
        local_symbol="SPY   260828C00765000",
        expiry="20260828",
        strike="765",
        right="C",
        currency="USD",
        side="BUY",
        contracts=1,
        price="5.20",
        multiplier="100",
    )
    values.update(overrides)
    return OptionFillEvidence(**values)


def test_long_call_roundtrip_uses_multiplier_100():
    result = account_closed_option_roundtrip(
        _fill(),
        _fill(execution_id="E2", side="SELL", price="5.35"),
    )
    assert result.realized_pnl == Decimal("15.00")
    assert result.ending_contracts == 0
    assert result.currency == "USD"
    assert result.multiplier == Decimal("100")


def test_loss_uses_multiplier_100():
    result = account_closed_option_roundtrip(
        _fill(),
        _fill(execution_id="E2", side="SELL", price="5.00"),
    )
    assert result.realized_pnl == Decimal("-20.00")


def test_contract_identity_drift_fails_closed():
    with pytest.raises(ValueError, match="identity changed"):
        account_closed_option_roundtrip(
            _fill(),
            _fill(execution_id="E2", side="SELL", con_id=900369378),
        )


def test_partial_roundtrip_fails_closed():
    with pytest.raises(ValueError, match="partial option"):
        account_closed_option_roundtrip(
            _fill(),
            _fill(execution_id="E2", side="SELL", contracts=2),
        )


def test_recovery_identity_includes_strike_right_multiplier():
    identity = option_recovery_identity(_fill())
    assert identity[0] == 900369377
    assert identity[1] == "SPY   260828C00765000"
    assert identity[2] == "20260828"
    assert identity[3] == Decimal("765")
    assert identity[4] == "C"
    assert identity[5] == "USD"
    assert identity[6] == Decimal("100")
