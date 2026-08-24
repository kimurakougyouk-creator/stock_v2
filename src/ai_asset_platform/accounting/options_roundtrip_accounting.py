"""Deterministic accounting evidence for one closed equity-option round-trip.

Pure accounting only: no broker connection and no order path. The identity is
strictly pinned across the open/close fills and option premium PnL is multiplied
by the contract multiplier.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class OptionFillEvidence:
    execution_id: str
    con_id: int
    local_symbol: str
    expiry: str
    strike: str
    right: str
    currency: str
    side: str
    contracts: int
    price: str
    multiplier: str


@dataclass(frozen=True)
class OptionRoundTripAccounting:
    realized_pnl: Decimal
    ending_contracts: int
    currency: str
    multiplier: Decimal


def _d(value, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    return parsed


def _validate_fill(fill: OptionFillEvidence) -> None:
    if not str(fill.execution_id).strip():
        raise ValueError("execution_id is required")
    if int(fill.con_id) <= 0:
        raise ValueError("con_id must be positive")
    if not str(fill.local_symbol).strip():
        raise ValueError("local_symbol is required")
    if not str(fill.expiry).strip():
        raise ValueError("expiry is required")
    if _d(fill.strike, "strike") <= 0:
        raise ValueError("strike must be positive")
    if str(fill.right).strip().upper() not in {"C", "P"}:
        raise ValueError("right must be C or P")
    if not str(fill.currency).strip():
        raise ValueError("currency is required")
    if str(fill.side).strip().upper() not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if int(fill.contracts) <= 0:
        raise ValueError("contracts must be positive")
    if _d(fill.price, "price") <= 0:
        raise ValueError("price must be positive")
    if _d(fill.multiplier, "multiplier") <= 0:
        raise ValueError("multiplier must be positive")


def option_recovery_identity(
    fill: OptionFillEvidence,
) -> tuple[int, str, str, Decimal, str, str, Decimal]:
    """Identity fields that must survive restart for a trusted option fill."""
    _validate_fill(fill)
    return (
        int(fill.con_id),
        str(fill.local_symbol).strip().upper(),
        str(fill.expiry).strip(),
        _d(fill.strike, "strike"),
        str(fill.right).strip().upper(),
        str(fill.currency).strip().upper(),
        _d(fill.multiplier, "multiplier"),
    )


def account_closed_option_roundtrip(
    open_fill: OptionFillEvidence,
    close_fill: OptionFillEvidence,
) -> OptionRoundTripAccounting:
    """Account one exact closed option round-trip, failing closed on mismatch."""
    _validate_fill(open_fill)
    _validate_fill(close_fill)
    if open_fill.execution_id == close_fill.execution_id:
        raise ValueError("execution ids must be unique")
    identity_open = option_recovery_identity(open_fill)
    identity_close = option_recovery_identity(close_fill)
    if identity_open != identity_close:
        raise ValueError("option contract identity changed across round-trip")
    if int(open_fill.contracts) != int(close_fill.contracts):
        raise ValueError("partial option round-trip is not trusted")

    open_side = str(open_fill.side).strip().upper()
    close_side = str(close_fill.side).strip().upper()
    if (open_side, close_side) not in {("BUY", "SELL"), ("SELL", "BUY")}:
        raise ValueError("round-trip sides must be opposite")

    open_price = _d(open_fill.price, "open price")
    close_price = _d(close_fill.price, "close price")
    contracts = Decimal(int(open_fill.contracts))
    multiplier = identity_open[-1]
    direction = Decimal(1) if open_side == "BUY" else Decimal(-1)
    realized = (close_price - open_price) * direction * contracts * multiplier
    return OptionRoundTripAccounting(
        realized_pnl=realized,
        ending_contracts=0,
        currency=identity_open[5],
        multiplier=multiplier,
    )
