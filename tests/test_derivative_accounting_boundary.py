import pytest

from ai_asset_platform.accounting.derivative_accounting_boundary import (
    VerifiedDerivativeAccountingSpec,
    derivative_paper_e2e_allowed,
)


def _spec(**overrides):
    values = dict(
        security_type="FUT",
        multiplier="50",
        expiry_or_settlement="202612",
        realized_pnl_verified=True,
        unrealized_pnl_verified=True,
        equity_drawdown_verified=True,
        restart_recovery_verified=True,
    )
    values.update(overrides)
    return VerifiedDerivativeAccountingSpec(**values)


def test_verified_future_boundary_allows_paper_e2e():
    assert derivative_paper_e2e_allowed(_spec()) is True


@pytest.mark.parametrize("security_type", ["", "STK", "CASH"])
def test_non_derivatives_are_rejected(security_type):
    with pytest.raises(ValueError, match="FUT or OPT"):
        derivative_paper_e2e_allowed(_spec(security_type=security_type))


@pytest.mark.parametrize("multiplier", ["", "0", "-1", "nan", "inf"])
def test_multiplier_must_be_positive(multiplier):
    with pytest.raises(ValueError, match="multiplier"):
        derivative_paper_e2e_allowed(_spec(multiplier=multiplier))


def test_expiry_or_settlement_is_required():
    with pytest.raises(ValueError, match="expiry_or_settlement"):
        derivative_paper_e2e_allowed(_spec(expiry_or_settlement=""))


@pytest.mark.parametrize(
    "field",
    [
        "realized_pnl_verified",
        "unrealized_pnl_verified",
        "equity_drawdown_verified",
        "restart_recovery_verified",
    ],
)
def test_every_accounting_evidence_gate_is_required(field):
    with pytest.raises(ValueError, match="remains blocked"):
        derivative_paper_e2e_allowed(_spec(**{field: False}))
