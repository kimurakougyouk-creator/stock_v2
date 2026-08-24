"""Read-only liquid-hours gate for the pinned SPY option.

The exact option ContractDetails supplied by IBKR is the source of trading
session metadata. This module creates no Order and calls no order API. It is
used immediately before the controlled Paper E2E so a market order is never
submitted outside the broker-reported liquid session.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_asset_platform.brokers.ibkr_option_paper_roundtrip import _verified_target
from ai_asset_platform.core.settings import SETTINGS


@dataclass(frozen=True)
class OptionSessionGateResult:
    resolved: bool
    time_zone_id: str | None
    liquid_hours: str | None
    checked_time: str | None
    open_now: bool
    matching_window: str | None
    errors: tuple[str, ...] = field(default_factory=tuple)
    real_order_sent: bool = False
    live_order_sent: bool = False

    @property
    def ready(self) -> bool:
        return self.resolved and self.open_now and not self.real_order_sent and not self.live_order_sent


def _parse_liquid_windows(raw: str, tz: ZoneInfo) -> list[tuple[datetime, datetime, str]]:
    windows: list[tuple[datetime, datetime, str]] = []
    for segment in str(raw or "").split(";"):
        segment = segment.strip()
        if not segment or "CLOSED" in segment.upper() or "-" not in segment:
            continue
        start_raw, end_raw = segment.split("-", 1)
        try:
            start = datetime.strptime(start_raw.strip(), "%Y%m%d:%H%M").replace(tzinfo=tz)
            end = datetime.strptime(end_raw.strip(), "%Y%m%d:%H%M").replace(tzinfo=tz)
        except ValueError:
            continue
        if end > start:
            windows.append((start, end, segment))
    return windows


def evaluate_liquid_hours(
    *,
    time_zone_id: str | None,
    liquid_hours: str | None,
    now: datetime | None = None,
) -> OptionSessionGateResult:
    tz_name = str(time_zone_id or "").strip()
    hours = str(liquid_hours or "").strip()
    if not tz_name or not hours:
        return OptionSessionGateResult(False, tz_name or None, hours or None, None, False, None, ("broker liquid-hours metadata is incomplete",))
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return OptionSessionGateResult(False, tz_name, hours, None, False, None, (f"unknown broker time zone: {tz_name}",))

    checked = datetime.now(tz) if now is None else now.astimezone(tz)
    windows = _parse_liquid_windows(hours, tz)
    for start, end, label in windows:
        if start <= checked < end:
            return OptionSessionGateResult(True, tz_name, hours, checked.isoformat(), True, label)
    return OptionSessionGateResult(True, tz_name, hours, checked.isoformat(), False, None)


def run_option_session_gate() -> OptionSessionGateResult:
    if not SETTINGS.enable_ibkr_paper:
        return OptionSessionGateResult(False, None, None, None, False, None, ("IBKR Paper is not explicitly enabled",))
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return OptionSessionGateResult(False, None, None, None, False, None, ("Live Trading safety lock is not intact",))
    endpoint_port, candidate, errors = _verified_target()
    if candidate is None:
        return OptionSessionGateResult(False, None, None, None, False, None, tuple(errors) + (f"exact option target unresolved on endpoint {endpoint_port}",))
    result = evaluate_liquid_hours(
        time_zone_id=getattr(candidate, "time_zone_id", None),
        liquid_hours=getattr(candidate, "liquid_hours", None),
    )
    return OptionSessionGateResult(
        result.resolved,
        result.time_zone_id,
        result.liquid_hours,
        result.checked_time,
        result.open_now,
        result.matching_window,
        tuple(errors) + result.errors,
        False,
        False,
    )


def main() -> int:
    result = run_option_session_gate()
    print("===== IBKR PAPER SPY OPTION LIQUID-HOURS GATE =====")
    print("RESOLVED             :", result.resolved)
    print("TIME ZONE            :", result.time_zone_id)
    print("CHECKED TIME         :", result.checked_time)
    print("OPEN NOW             :", result.open_now)
    print("MATCHING WINDOW      :", result.matching_window)
    print("LIQUID HOURS         :", result.liquid_hours)
    print("ERRORS               :", list(result.errors))
    print("REAL ORDER SENT      :", result.real_order_sent)
    print("LIVE ORDER SENT      :", result.live_order_sent)
    return 0 if result.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
