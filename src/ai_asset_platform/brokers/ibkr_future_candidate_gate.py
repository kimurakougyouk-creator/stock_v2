"""Fail-closed selection of exactly one broker-resolved futures contract.

This module never connects to IBKR and never creates an Order. It only reduces
read-only ContractDetails evidence to one explicit FUT candidate so later
What-If work cannot invent expiry, multiplier, venue, or conId.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_future_discovery import (
    IbkrFutureCandidate,
    IbkrFutureDiscoveryResult,
)


@dataclass(frozen=True)
class VerifiedFutureCandidate:
    symbol: str
    local_symbol: str
    exchange: str
    currency: str
    expiry: str
    multiplier: str
    con_id: int
    min_tick: float
    time_zone_id: str | None
    trading_hours: str | None
    liquid_hours: str | None


def select_verified_future_candidate(
    result: IbkrFutureDiscoveryResult,
    *,
    local_symbol: str | None = None,
    expiry: str | None = None,
) -> VerifiedFutureCandidate:
    """Select exactly one FUT candidate from broker evidence or fail closed."""
    if not result.connected or result.order_sent:
        raise ValueError("futures discovery evidence is not connected/read-only")
    if not result.candidates:
        raise ValueError("futures discovery returned no candidates")
    if bool(local_symbol) == bool(expiry):
        raise ValueError("provide exactly one of local_symbol or expiry")

    target_local = str(local_symbol or "").strip().upper()
    target_expiry = str(expiry or "").strip()
    matches: list[IbkrFutureCandidate] = []
    for candidate in result.candidates:
        if target_local and str(candidate.local_symbol or "").strip().upper() == target_local:
            matches.append(candidate)
        if target_expiry and str(candidate.expiry or "").strip() == target_expiry:
            matches.append(candidate)

    if len(matches) != 1:
        raise ValueError(f"futures candidate selection must resolve exactly one contract; got {len(matches)}")

    candidate = matches[0]
    if not candidate.local_symbol:
        raise ValueError("broker future candidate is missing local_symbol")
    if not candidate.expiry:
        raise ValueError("broker future candidate is missing expiry")
    if not candidate.multiplier:
        raise ValueError("broker future candidate is missing multiplier")
    if not candidate.con_id or int(candidate.con_id) <= 0:
        raise ValueError("broker future candidate is missing positive con_id")
    if candidate.min_tick is None or float(candidate.min_tick) <= 0:
        raise ValueError("broker future candidate is missing positive min_tick")

    return VerifiedFutureCandidate(
        symbol=str(candidate.symbol).strip().upper(),
        local_symbol=str(candidate.local_symbol).strip(),
        exchange=str(candidate.exchange).strip().upper(),
        currency=str(candidate.currency).strip().upper(),
        expiry=str(candidate.expiry).strip(),
        multiplier=str(candidate.multiplier).strip(),
        con_id=int(candidate.con_id),
        min_tick=float(candidate.min_tick),
        time_zone_id=candidate.time_zone_id,
        trading_hours=candidate.trading_hours,
        liquid_hours=candidate.liquid_hours,
    )
