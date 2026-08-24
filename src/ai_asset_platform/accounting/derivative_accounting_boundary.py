"""Fail-closed accounting boundary for derivatives.

Futures/options must not enter the trusted stock/ETF accounting path until
product-specific accounting semantics have been explicitly verified.
This module does not create or transmit broker orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class VerifiedDerivativeAccountingSpec:
    security_type: str
    multiplier: str
    expiry_or_settlement: str
    realized_pnl_verified: bool
    unrealized_pnl_verified: bool
    equity_drawdown_verified: bool
    restart_recovery_verified: bool


def _positive_decimal(value: str, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{name} must be a positive number")
    return parsed


def validate_derivative_accounting_boundary(
    spec: VerifiedDerivativeAccountingSpec,
) -> VerifiedDerivativeAccountingSpec:
    """Require explicit derivative accounting evidence before Paper E2E."""
    security_type = str(spec.security_type).strip().upper()
    if security_type not in {"FUT", "OPT"}:
        raise ValueError("derivative security_type must be FUT or OPT")
    _positive_decimal(spec.multiplier, "derivative multiplier")
    if not str(spec.expiry_or_settlement).strip():
        raise ValueError("derivative expiry_or_settlement is required")

    required = {
        "realized PnL": spec.realized_pnl_verified,
        "unrealized PnL": spec.unrealized_pnl_verified,
        "equity/drawdown": spec.equity_drawdown_verified,
        "restart recovery": spec.restart_recovery_verified,
    }
    missing = [name for name, verified in required.items() if verified is not True]
    if missing:
        raise ValueError(
            "derivative accounting boundary remains blocked: " + ", ".join(missing)
        )
    return spec


def derivative_paper_e2e_allowed(spec: VerifiedDerivativeAccountingSpec) -> bool:
    """Return True only after every derivative accounting boundary is verified."""
    validate_derivative_accounting_boundary(spec)
    return True
