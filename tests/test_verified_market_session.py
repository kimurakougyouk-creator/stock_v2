from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_asset_platform.execution.verified_market_session import (
    evaluate_verified_market_session,
)


NY = ZoneInfo("America/New_York")
TOKYO = ZoneInfo("Asia/Tokyo")


def test_us_core_session_allows_aapl_during_regular_hours():
    result = evaluate_verified_market_session(
        "AAPL",
        now=datetime(2026, 9, 1, 10, 0, tzinfo=NY),
    )
    assert result.allowed is True
    assert result.session == "CORE_OPEN"


def test_us_core_session_blocks_before_open():
    result = evaluate_verified_market_session(
        "AAPL",
        now=datetime(2026, 9, 1, 9, 29, tzinfo=NY),
    )
    assert result.allowed is False
    assert result.session == "CLOSED_OUTSIDE_CORE"


def test_us_exchange_holiday_blocks_even_on_weekday():
    result = evaluate_verified_market_session(
        "SPY",
        now=datetime(2026, 9, 7, 10, 0, tzinfo=NY),
    )
    assert result.allowed is False
    assert result.session == "CLOSED_HOLIDAY"


def test_us_early_close_blocks_after_one_pm():
    before = evaluate_verified_market_session(
        "SPY",
        now=datetime(2026, 11, 27, 12, 59, tzinfo=NY),
    )
    after = evaluate_verified_market_session(
        "SPY",
        now=datetime(2026, 11, 27, 13, 0, tzinfo=NY),
    )
    assert before.allowed is True
    assert after.allowed is False


def test_tse_morning_and_afternoon_sessions_allow_9432():
    morning = evaluate_verified_market_session(
        "9432.T",
        now=datetime(2026, 9, 1, 10, 0, tzinfo=TOKYO),
    )
    afternoon = evaluate_verified_market_session(
        "9432.T",
        now=datetime(2026, 9, 1, 15, 0, tzinfo=TOKYO),
    )
    assert morning.allowed is True
    assert morning.session == "MORNING_OPEN"
    assert afternoon.allowed is True
    assert afternoon.session == "AFTERNOON_OPEN"


def test_tse_lunch_break_blocks_order_transmission():
    result = evaluate_verified_market_session(
        "9432.T",
        now=datetime(2026, 9, 1, 12, 0, tzinfo=TOKYO),
    )
    assert result.allowed is False
    assert result.session == "CLOSED_OUTSIDE_AUCTION"


def test_tse_market_holiday_blocks_cash_order():
    result = evaluate_verified_market_session(
        "9432.T",
        now=datetime(2026, 9, 21, 10, 0, tzinfo=TOKYO),
    )
    assert result.allowed is False
    assert result.session == "CLOSED_HOLIDAY"


def test_unsupported_calendar_year_fails_closed():
    result = evaluate_verified_market_session(
        "AAPL",
        now=datetime(2028, 1, 4, 10, 0, tzinfo=NY),
    )
    assert result.allowed is False
    assert result.session == "UNSUPPORTED_CALENDAR_YEAR"


def test_unregistered_symbol_fails_closed():
    result = evaluate_verified_market_session(
        "MSFT",
        now=datetime(2026, 9, 1, 10, 0, tzinfo=NY),
    )
    assert result.allowed is False
    assert result.session == "UNSUPPORTED_SYMBOL"


def test_market_session_guard_contains_no_broker_mutation_calls():
    source = (
        Path(__file__).parents[1]
        / "src"
        / "ai_asset_platform"
        / "execution"
        / "verified_market_session.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "placeOrder(",
        "cancelOrder(",
        "reqOpenOrders(",
        "reqAllOpenOrders(",
        "enable_live_trading=True",
        "live_trading_unlocked=True",
    ):
        assert forbidden not in source
