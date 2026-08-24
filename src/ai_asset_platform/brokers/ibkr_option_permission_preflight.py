"""No-real-order permission/specification preflight for pinned SPY option.

Uses exact ContractDetails plus the already established IBKR What-If mechanism.
It verifies the broker still resolves the pinned contract, reports MKT support,
provides liquid-hours metadata, and accepts a one-contract What-If preview.
No real Paper or Live order is submitted.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ai_asset_platform.brokers.ibkr_option_paper_roundtrip import (
    CON_ID,
    EXPIRY,
    LOCAL_SYMBOL,
    MULTIPLIER,
    RIGHT,
    STRIKE,
    _verified_target,
)
from ai_asset_platform.brokers.ibkr_option_whatif import run_option_whatif
from ai_asset_platform.core.settings import SETTINGS


@dataclass(frozen=True)
class OptionPermissionPreflightResult:
    ready: bool
    exact_target_resolved: bool
    market_order_supported: bool
    smart_route_supported: bool
    liquid_hours_metadata_ready: bool
    min_tick: float | None
    time_zone_id: str | None
    liquid_hours: str | None
    whatif_ready: bool
    whatif_margin_change: float | None
    errors: tuple[str, ...] = field(default_factory=tuple)
    real_order_sent: bool = False
    live_order_sent: bool = False


def _tokenized(raw: object) -> set[str]:
    text = str(raw or "").upper().replace(";", ",")
    return {item.strip() for item in text.split(",") if item.strip()}


def run_option_permission_preflight() -> OptionPermissionPreflightResult:
    if not SETTINGS.enable_ibkr_paper:
        return OptionPermissionPreflightResult(False, False, False, False, False, None, None, None, False, None, ("IBKR Paper is not explicitly enabled",))
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return OptionPermissionPreflightResult(False, False, False, False, False, None, None, None, False, None, ("Live Trading safety lock is not intact",))

    port, candidate, discovery_errors = _verified_target()
    exact = bool(
        candidate is not None
        and candidate.con_id == CON_ID
        and candidate.local_symbol == LOCAL_SYMBOL
        and candidate.expiry == EXPIRY
        and candidate.strike == STRIKE
        and str(candidate.right).upper() == RIGHT
        and str(candidate.multiplier) == MULTIPLIER
    )
    order_types = _tokenized(getattr(candidate, "order_types", None)) if candidate else set()
    valid_exchanges = _tokenized(getattr(candidate, "valid_exchanges", None)) if candidate else set()
    market_supported = "MKT" in order_types
    smart_supported = bool(candidate and (str(getattr(candidate, "exchange", "")).upper() == "SMART" or "SMART" in valid_exchanges))
    time_zone_id = str(getattr(candidate, "time_zone_id", "") or "") or None if candidate else None
    liquid_hours = str(getattr(candidate, "liquid_hours", "") or "") or None if candidate else None
    hours_ready = bool(time_zone_id and liquid_hours)
    min_tick_raw = getattr(candidate, "min_tick", None) if candidate else None
    try:
        min_tick = float(min_tick_raw) if min_tick_raw is not None and float(min_tick_raw) > 0 else None
    except (TypeError, ValueError):
        min_tick = None

    preview = run_option_whatif()
    errors = tuple(discovery_errors) + tuple(preview.errors)
    whatif_exact = bool(
        preview.ready
        and preview.con_id == CON_ID
        and preview.local_symbol == LOCAL_SYMBOL
        and preview.expiry == EXPIRY
        and preview.strike == STRIKE
        and str(preview.right).upper() == RIGHT
        and str(preview.multiplier) == MULTIPLIER
        and not preview.real_order_sent
        and not preview.live_order_sent
    )
    ready = bool(
        exact
        and market_supported
        and smart_supported
        and hours_ready
        and min_tick is not None
        and whatif_exact
    )
    return OptionPermissionPreflightResult(
        ready,
        exact,
        market_supported,
        smart_supported,
        hours_ready,
        min_tick,
        time_zone_id,
        liquid_hours,
        whatif_exact,
        preview.margin_change,
        errors,
        False,
        False,
    )


def main() -> int:
    result = run_option_permission_preflight()
    print("===== IBKR PAPER SPY OPTION PERMISSION/SPEC PREFLIGHT =====")
    print("READY                       :", result.ready)
    print("PINNED TARGET RESOLVED      :", result.exact_target_resolved)
    print("MKT ORDER SUPPORTED         :", result.market_order_supported)
    print("SMART ROUTE SUPPORTED       :", result.smart_route_supported)
    print("MIN TICK                    :", result.min_tick)
    print("LIQUID HOURS METADATA READY :", result.liquid_hours_metadata_ready)
    print("TIME ZONE                   :", result.time_zone_id)
    print("LIQUID HOURS                :", result.liquid_hours)
    print("WHAT-IF READY               :", result.whatif_ready)
    print("WHAT-IF MARGIN CHANGE       :", result.whatif_margin_change)
    print("ERRORS                      :", list(result.errors))
    print("REAL ORDER SENT             :", result.real_order_sent)
    print("LIVE ORDER SENT             :", result.live_order_sent)
    return 0 if result.ready and not result.real_order_sent and not result.live_order_sent else 2


if __name__ == "__main__":
    raise SystemExit(main())
