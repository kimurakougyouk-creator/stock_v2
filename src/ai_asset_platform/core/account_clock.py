"""Explicit account-calendar clock helpers."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_asset_platform.core.settings import PlatformSettings, SETTINGS


class AccountClockError(ValueError):
    pass


def account_zone(settings: PlatformSettings = SETTINGS) -> ZoneInfo:
    name = str(settings.account_timezone).strip()
    if not name:
        raise AccountClockError("account_timezone is required")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise AccountClockError(f"unknown account_timezone: {name}") from exc


def account_now(settings: PlatformSettings = SETTINGS) -> datetime:
    return datetime.now(account_zone(settings))


def account_today(settings: PlatformSettings = SETTINGS) -> date:
    return account_now(settings).date()
