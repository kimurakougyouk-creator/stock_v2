"""Evidence-bounded futures capability scope.

The verified broker evidence covers only one ESU6 long round-trip in Paper:
BUY 1 then SELL 1 to flat. This module deliberately does not claim general ES
or futures support, short-first trading, multi-contract sizing, roll/expiry
handling, overnight holding, or Live trading.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedFutureScope:
    local_symbol: str
    con_id: int
    long_only: bool
    quantity: int
    start_flat_required: bool
    end_flat_required: bool
    overnight_holding_supported: bool
    expiry_or_roll_supported: bool
    live_supported: bool


ESU6_LONG_ROUNDTRIP_PAPER_SCOPE = VerifiedFutureScope(
    local_symbol="ESU6",
    con_id=649180671,
    long_only=True,
    quantity=1,
    start_flat_required=True,
    end_flat_required=True,
    overnight_holding_supported=False,
    expiry_or_roll_supported=False,
    live_supported=False,
)


def validate_esu6_long_roundtrip_scope(
    *,
    local_symbol: str,
    con_id: int,
    open_side: str,
    close_side: str,
    quantity: int,
    start_quantity: float,
    end_quantity: float,
) -> bool:
    """Fail closed outside the exact futures Paper evidence boundary."""
    if str(local_symbol).strip().upper() != "ESU6" or int(con_id) != 649180671:
        raise ValueError("verified futures scope is pinned to ESU6/conId 649180671")
    if (str(open_side).upper(), str(close_side).upper()) != ("BUY", "SELL"):
        raise ValueError("verified futures scope is long-only BUY then SELL")
    if int(quantity) != 1:
        raise ValueError("verified futures scope is exactly one contract")
    if abs(float(start_quantity)) > 1e-9 or abs(float(end_quantity)) > 1e-9:
        raise ValueError("verified futures round-trip must start and end flat")
    return True
