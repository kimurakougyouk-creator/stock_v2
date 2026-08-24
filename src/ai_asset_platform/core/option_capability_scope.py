"""Evidence-bounded option capability scope.

The verified Paper evidence covers only one long SPY call opened and closed
intraday before expiry. This module deliberately does not claim general US
option support, short-option support, exercise/assignment handling, expiry-day
holding, or Live trading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class VerifiedOptionScope:
    underlying: str
    long_only: bool
    same_session_close_required: bool
    hold_through_expiry_allowed: bool
    exercise_supported: bool
    assignment_supported: bool
    live_supported: bool


SPY_LONG_INTRADAY_PAPER_SCOPE = VerifiedOptionScope(
    underlying="SPY",
    long_only=True,
    same_session_close_required=True,
    hold_through_expiry_allowed=False,
    exercise_supported=False,
    assignment_supported=False,
    live_supported=False,
)


def validate_spy_long_intraday_roundtrip_scope(
    *,
    underlying: str,
    open_side: str,
    close_side: str,
    start_quantity: float,
    end_quantity: float,
    open_date: date,
    close_date: date,
    expiry: str,
) -> bool:
    """Fail closed unless the observed round-trip stays inside verified scope."""
    if str(underlying).strip().upper() != "SPY":
        raise ValueError("verified option scope is pinned to SPY")
    if (str(open_side).upper(), str(close_side).upper()) != ("BUY", "SELL"):
        raise ValueError("verified option scope is long-only BUY then SELL")
    if abs(float(start_quantity)) > 1e-9 or abs(float(end_quantity)) > 1e-9:
        raise ValueError("verified option round-trip must start and end flat")
    if open_date != close_date:
        raise ValueError("verified option scope requires same-session close")
    try:
        expiry_date = datetime.strptime(str(expiry), "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError("option expiry must use YYYYMMDD") from exc
    if open_date >= expiry_date or close_date >= expiry_date:
        raise ValueError("expiry-day or post-expiry holding is outside verified scope")
    return True
