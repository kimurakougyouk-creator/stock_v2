from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.account_calendar_ledger import (
    daily_order_count,
    position_holding_days,
    repurchase_cooldown_remaining_minutes,
)


def _settings():
    return replace(SETTINGS, account_timezone="Asia/Tokyo")


def _row(*, ticker="SPY", side="BUY", shares=1, created_at):
    return {
        "ticker": ticker,
        "side": side,
        "shares": shares,
        "created_at": created_at,
        "status": "FILLED",
        "mode": "IBKR_PAPER",
    }


def test_daily_count_maps_utc_timestamp_to_tokyo_account_day():
    rows = [_row(created_at="2026-08-21T15:30:00+00:00")]
    now = datetime(2026, 8, 22, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert daily_order_count(rows, side="BUY", settings=_settings(), now=now) == 1


def test_cooldown_handles_timezone_aware_confirmed_fill_without_naive_subtraction():
    rows = [_row(side="SELL", created_at="2026-08-22T10:00:00+09:00")]
    now = datetime(2026, 8, 22, 10, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert repurchase_cooldown_remaining_minutes(
        rows,
        ticker="SPY",
        cooldown_minutes=60,
        settings=_settings(),
        now=now,
    ) == 30


def test_holding_days_handles_timezone_aware_fifo_lots():
    rows = [
        _row(created_at="2026-08-20T09:00:00+09:00", shares=2),
        _row(side="SELL", created_at="2026-08-21T09:00:00+09:00", shares=1),
    ]
    now = datetime(2026, 8, 22, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    assert position_holding_days(rows, ticker="SPY", settings=_settings(), now=now) == 2


def test_holding_days_fails_closed_on_sell_exceeding_confirmed_lots():
    rows = [_row(side="SELL", created_at="2026-08-22T10:00:00+09:00")]
    with pytest.raises(ValueError, match="exceeds"):
        position_holding_days(rows, ticker="SPY", settings=_settings())
