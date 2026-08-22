"""Timezone-safe durable-ledger helpers for active Paper risk/runtime checks."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_asset_platform.core.account_clock import account_now
from ai_asset_platform.core.settings import PlatformSettings, SETTINGS


class AccountCalendarLedgerError(ValueError):
    pass


def _zone(settings: PlatformSettings) -> ZoneInfo:
    try:
        return ZoneInfo(str(settings.account_timezone).strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AccountCalendarLedgerError("account_timezone is invalid") from exc


def record_time_in_account_zone(record: dict, settings: PlatformSettings = SETTINGS) -> datetime:
    raw = record.get("created_at")
    if not raw:
        raise AccountCalendarLedgerError("ledger record is missing created_at")
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError) as exc:
        raise AccountCalendarLedgerError("ledger record has invalid created_at") from exc
    zone = _zone(settings)
    if parsed.tzinfo is None:
        # Legacy rows had no offset. Interpret them in the explicitly configured
        # account calendar rather than whichever timezone the Linux host uses.
        return parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def daily_order_count(
    records: list[dict],
    *,
    side: str,
    settings: PlatformSettings = SETTINGS,
    now: datetime | None = None,
) -> int:
    target_side = str(side).strip().upper()
    if target_side not in {"BUY", "SELL"}:
        raise AccountCalendarLedgerError("side must be BUY or SELL")
    current = now.astimezone(_zone(settings)) if now is not None else account_now(settings)
    count = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("side", "")).strip().upper() != target_side:
            continue
        try:
            recorded = record_time_in_account_zone(record, settings)
        except AccountCalendarLedgerError:
            # A malformed actionable record cannot be safely assigned to a day.
            raise
        if recorded.date() == current.date():
            count += 1
    return count


def repurchase_cooldown_remaining_minutes(
    records: list[dict],
    *,
    ticker: str,
    cooldown_minutes: int,
    settings: PlatformSettings = SETTINGS,
    now: datetime | None = None,
) -> int:
    cooldown = int(cooldown_minutes)
    if cooldown <= 0:
        return 0
    target = str(ticker).strip().upper()
    current = now.astimezone(_zone(settings)) if now is not None else account_now(settings)
    latest: datetime | None = None
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("ticker", "")).strip().upper() != target:
            continue
        if str(record.get("side", "")).strip().upper() != "SELL":
            continue
        recorded = record_time_in_account_zone(record, settings)
        if latest is None or recorded > latest:
            latest = recorded
    if latest is None:
        return 0
    elapsed = (current - latest).total_seconds()
    if elapsed < 0:
        return cooldown
    remaining = cooldown * 60 - elapsed
    if remaining <= 0:
        return 0
    return int((remaining + 59) // 60)


def position_holding_days(
    records: list[dict],
    *,
    ticker: str,
    settings: PlatformSettings = SETTINGS,
    now: datetime | None = None,
) -> int | None:
    """Return FIFO holding age of the oldest remaining confirmed lot."""
    target = str(ticker).strip().upper()
    current = now.astimezone(_zone(settings)) if now is not None else account_now(settings)
    lots: list[list[object]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("ticker", "")).strip().upper() != target:
            continue
        side = str(record.get("side", "")).strip().upper()
        try:
            shares = int(record.get("shares"))
        except (TypeError, ValueError) as exc:
            raise AccountCalendarLedgerError("ledger shares must be whole") from exc
        if shares <= 0 or side not in {"BUY", "SELL"}:
            raise AccountCalendarLedgerError("ledger position record is invalid")
        recorded = record_time_in_account_zone(record, settings)
        if side == "BUY":
            lots.append([shares, recorded])
            continue
        remaining = shares
        while remaining > 0 and lots:
            lot_qty = int(lots[0][0])
            if remaining >= lot_qty:
                remaining -= lot_qty
                lots.pop(0)
            else:
                lots[0][0] = lot_qty - remaining
                remaining = 0
        if remaining > 0:
            raise AccountCalendarLedgerError("confirmed SELL exceeds prior confirmed BUY lots")
    if not lots:
        return None
    oldest = lots[0][1]
    if not isinstance(oldest, datetime):
        raise AccountCalendarLedgerError("oldest lot timestamp is invalid")
    elapsed = (current - oldest).total_seconds()
    if elapsed <= 0:
        return 0
    return int(elapsed // 86_400)
