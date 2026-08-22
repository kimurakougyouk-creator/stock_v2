from datetime import datetime
from zoneinfo import ZoneInfo

from ai_asset_platform.brokers.ibkr_extended_close_e2e import is_us_extended_session_open

ET = ZoneInfo("America/New_York")


def test_premarket_is_open_weekday():
    assert is_us_extended_session_open(datetime(2026, 8, 21, 8, 0, tzinfo=ET))


def test_regular_hours_are_not_extended_session():
    assert not is_us_extended_session_open(datetime(2026, 8, 21, 12, 0, tzinfo=ET))


def test_after_hours_is_open_weekday():
    assert is_us_extended_session_open(datetime(2026, 8, 21, 16, 30, tzinfo=ET))


def test_weekend_is_closed():
    assert not is_us_extended_session_open(datetime(2026, 8, 22, 16, 30, tzinfo=ET))
