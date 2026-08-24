"""Evidence-based IBKR Paper capability registry.

A capability may be marked VERIFIED only when the repository has direct Paper
broker evidence for that exact behavior. Unsupported lifecycle behavior stays
explicitly blocked instead of being inferred from a successful round-trip.
No broker API is called from this module.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedCapability:
    name: str
    verified: bool
    scope: str
    evidence: str


SPY_OPTION_PAPER_CAPABILITIES = (
    VerifiedCapability(
        "contract_resolution",
        True,
        "Pinned SPY 2026-08-28 765C, SMART/USD, multiplier 100, conId 900369377",
        "IBKR ContractDetails and repeated pre-open audit resolved the exact pinned contract",
    ),
    VerifiedCapability(
        "what_if_preview",
        True,
        "Pinned SPY option Paper account",
        "IBKR What-If preview received for the exact pinned contract",
    ),
    VerifiedCapability(
        "buy_sell_roundtrip",
        True,
        "Exactly one long contract opened then closed in Paper",
        "BUY 1 @ 4.08 then SELL 1 @ 4.07; broker position recovered flat",
    ),
    VerifiedCapability(
        "multiplier_realized_pnl",
        True,
        "Closed pinned SPY option round-trip, multiplier 100",
        "Recovered gross realized PnL = -1.00 USD",
    ),
    VerifiedCapability(
        "flat_unrealized_pnl",
        True,
        "Post-close flat state only",
        "Broker position 0 implies unrealized PnL 0 for the closed contract",
    ),
    VerifiedCapability(
        "equity_drawdown_delta",
        True,
        "Closed pinned round-trip delta, before commissions/fees",
        "Multiplier-aware accounting derives equity delta -1.00 USD and drawdown 1.00 USD",
    ),
    VerifiedCapability(
        "restart_execution_recovery",
        True,
        "Exact historical executions for the pinned contract",
        "Two IBKR execIds were recovered after restart and matched BUY1->SELL1",
    ),
    VerifiedCapability(
        "exercise",
        False,
        "Option lifecycle",
        "No direct Paper exercise evidence",
    ),
    VerifiedCapability(
        "assignment",
        False,
        "Option lifecycle",
        "No direct Paper assignment evidence",
    ),
    VerifiedCapability(
        "expiration_settlement",
        False,
        "Option lifecycle",
        "No direct Paper expiration/settlement evidence",
    ),
    VerifiedCapability(
        "short_option",
        False,
        "Opening short option positions",
        "Only long BUY-to-open then SELL-to-close was proven",
    ),
    VerifiedCapability(
        "multi_leg_option",
        False,
        "Spreads/combos/multi-leg orders",
        "No direct Paper multi-leg evidence",
    ),
)


def verified_option_capability_names() -> frozenset[str]:
    return frozenset(item.name for item in SPY_OPTION_PAPER_CAPABILITIES if item.verified)


def blocked_option_capability_names() -> frozenset[str]:
    return frozenset(item.name for item in SPY_OPTION_PAPER_CAPABILITIES if not item.verified)


def require_verified_option_capability(name: str) -> VerifiedCapability:
    requested = str(name).strip()
    for item in SPY_OPTION_PAPER_CAPABILITIES:
        if item.name == requested:
            if not item.verified:
                raise ValueError(f"IBKR Paper option capability is not verified: {requested}")
            return item
    raise ValueError(f"unknown IBKR Paper option capability: {requested}")
