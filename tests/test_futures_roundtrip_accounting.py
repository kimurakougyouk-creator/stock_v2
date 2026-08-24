from decimal import Decimal

import pytest

from ai_asset_platform.accounting.futures_roundtrip_accounting import (
    FuturesFillEvidence,
    account_closed_futures_roundtrip,
    recovery_identity,
)


def _fill(**overrides):
    values = dict(
        execution_id="exec-open",
        con_id=649180671,
        local_symbol="ESU6",
        expiry="20260918",
        currency="USD",
        side="BUY",
        contracts=1,
        price="7668.25",
        multiplier="50",
    )
    values.update(overrides)
    return FuturesFillEvidence(**values)


def test_es_u6_roundtrip_realized_pnl_uses_multiplier():
    result = account_closed_futures_roundtrip(
        _fill(),
        _fill(execution_id="exec-close", side="SELL", price="7667.75"),
    )
    assert result.realized_pnl == Decimal("-25.00")
    assert result.ending_contracts == 0
    assert result.currency == "USD"
    assert result.multiplier == Decimal("50")


def test_short_roundtrip_direction_is_correct():
    result = account_closed_futures_roundtrip(
        _fill(side="SELL", price="7668.25"),
        _fill(execution_id="exec-close", side="BUY", price="7667.75"),
    )
    assert result.realized_pnl == Decimal("25.00")


def test_contract_identity_mismatch_blocks_accounting():
    with pytest.raises(ValueError, match="identity changed"):
        account_closed_futures_roundtrip(
            _fill(),
            _fill(execution_id="exec-close", side="SELL", con_id=1),
        )


def test_partial_roundtrip_is_not_trusted():
    with pytest.raises(ValueError, match="partial"):
        account_closed_futures_roundtrip(
            _fill(contracts=2),
            _fill(execution_id="exec-close", side="SELL", contracts=1),
        )


def test_restart_recovery_identity_preserves_derivative_fields():
    assert recovery_identity(_fill()) == (
        649180671,
        "ESU6",
        "20260918",
        "USD",
        Decimal("50"),
    )
