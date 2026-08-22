from datetime import datetime, timezone

import pytest

from ai_asset_platform.brokers.ibkr_overnight_session import (
    is_broker_session_open,
    parse_ibkr_trading_intervals,
)


def test_broker_reported_overnight_interval_is_open_inside_window():
    raw = "20260823:2000-20260824:0350"
    server_time = datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc)  # 01:00 ET
    assert is_broker_session_open(
        server_time_utc=server_time,
        trading_hours=raw,
        timezone_id="America/New_York",
    ) is True


def test_closed_segment_is_not_open():
    assert parse_ibkr_trading_intervals(
        "20260824:CLOSED",
        "America/New_York",
    ) == ()
    server_time = datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc)
    assert is_broker_session_open(
        server_time_utc=server_time,
        trading_hours="20260824:CLOSED",
        timezone_id="America/New_York",
    ) is False


def test_multiple_windows_are_supported():
    intervals = parse_ibkr_trading_intervals(
        "20260823:2000-20260824:0100,20260824:0130-20260824:0350",
        "America/New_York",
    )
    assert len(intervals) == 2


def test_malformed_broker_hours_fail_closed():
    with pytest.raises(ValueError):
        parse_ibkr_trading_intervals(
            "20260823:not-a-window",
            "America/New_York",
        )


def test_naive_server_time_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        is_broker_session_open(
            server_time_utc=datetime(2026, 8, 24, 5, 0),
            trading_hours="20260823:2000-20260824:0350",
            timezone_id="America/New_York",
        )
