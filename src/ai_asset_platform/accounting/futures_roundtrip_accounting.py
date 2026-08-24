"""Deterministic accounting evidence for one closed futures round-trip.

This module is pure accounting logic. It does not connect to IBKR and cannot
create or transmit orders. It exists to verify multiplier-aware futures PnL and
restart-safe persisted identity fields before FUTURE capability promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class FuturesFillEvidence:
    execution_id: str
    con_id: int
    local_symbol: str
    expiry: str
    currency: str
    side: str
    contracts: int
    price: str
    multiplier: str


@dataclass(frozen=True)
class FuturesRoundTripAccounting:
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


def _validate_fill(fill: FuturesFillEvidence) -> None:
    if not str(fill.execution_id).strip():
        raise ValueError("execution_id is required")
    if int(fill.con_id) <= 0:
        raise ValueError("con_id must be positive")
    if not str(fill.local_symbol).strip():
        raise ValueError("local_symbol is required")
    if not str(fill.expiry).strip():
        raise ValueError("expiry is required")
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


def account_closed_futures_roundtrip(
    open_fill: FuturesFillEvidence,
    close_fill: FuturesFillEvidence,
) -> FuturesRoundTripAccounting:
    """Account one exact closed futures round-trip, fail-closed on mismatch."""
    _validate_fill(open_fill)
    _validate_fill(close_fill)
    if open_fill.execution_id == close_fill.execution_id:
        raise ValueError("execution ids must be unique")
    identity_open = (
        int(open_fill.con_id), str(open_fill.local_symbol).strip().upper(),
        str(open_fill.expiry).strip(), str(open_fill.currency).strip().upper(),
        _d(open_fill.multiplier, "multiplier"),
    )
    identity_close = (
        int(close_fill.con_id), str(close_fill.local_symbol).strip().upper(),
        str(close_fill.expiry).strip(), str(close_fill.currency).strip().upper(),
        _d(close_fill.multiplier, "multiplier"),
    )
    if identity_open != identity_close:
        raise ValueError("futures contract identity changed across round-trip")
    if int(open_fill.contracts) != int(close_fill.contracts):
        raise ValueError("partial futures round-trip is not trusted")
    open_side = str(open_fill.side).strip().upper()
    close_side = str(close_fill.side).strip().upper()
    if (open_side, close_side) not in {("BUY", "SELL"), ("SELL", "BUY")}:
        raise ValueError("round-trip sides must be opposite")

    open_price = _d(open_fill.price, "open price")
    close_price = _d(close_fill.price, "close price")
    contracts = Decimal(int(open_fill.contracts))
    multiplier = identity_open[4]
    direction = Decimal(1) if open_side == "BUY" else Decimal(-1)
    realized = (close_price - open_price) * direction * contracts * multiplier
    return FuturesRoundTripAccounting(
        realized_pnl=realized,
        ending_contracts=0,
        currency=identity_open[3],
        multiplier=multiplier,
    )


def recovery_identity(fill: FuturesFillEvidence) -> tuple[int, str, str, str, Decimal]:
    """Fields that must survive persistence/restart for trusted futures recovery."""
    _validate_fill(fill)
    return (
        int(fill.con_id),
        str(fill.local_symbol).strip().upper(),
        str(fill.expiry).strip(),
        str(fill.currency).strip().upper(),
        _d(fill.multiplier, "multiplier"),
    )
