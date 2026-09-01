"""Fail-closed core-session guard for the currently verified Paper pilot universe.

The guard is deliberately offline and deterministic.  It does not connect to a
broker and never creates, changes, cancels, or transmits orders.  It permits the
current verified US equity symbols only during the US core session and TSE cash
symbols only during TSE auction sessions.  Official exchange holidays and known
NYSE early closes are pinned for supported calendar years; an unknown year fails
closed until the calendar is explicitly reviewed and extended.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


_US_ZONE = ZoneInfo("America/New_York")
_JPX_ZONE = ZoneInfo("Asia/Tokyo")
_VERIFIED_US_EQUITIES = frozenset({"AAPL", "SPY"})
_SUPPORTED_YEARS = frozenset({2026, 2027})

# NYSE official holiday calendar for the supported years.
_US_HOLIDAYS = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),
        date(2027, 7, 5),
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),
    }
)

# NYSE official 1:00 p.m. ET early closes in the supported years.
_US_EARLY_CLOSES = frozenset(
    {
        date(2026, 11, 27),
        date(2026, 12, 24),
        date(2027, 11, 26),
    }
)

# JPX official cash-market holidays for the supported years.  Weekend dates are
# included where JPX lists them; weekend blocking also applies independently.
_JPX_HOLIDAYS = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 12),
        date(2026, 2, 11),
        date(2026, 2, 23),
        date(2026, 3, 20),
        date(2026, 4, 29),
        date(2026, 5, 3),
        date(2026, 5, 4),
        date(2026, 5, 5),
        date(2026, 5, 6),
        date(2026, 7, 20),
        date(2026, 8, 11),
        date(2026, 9, 21),
        date(2026, 9, 22),
        date(2026, 9, 23),
        date(2026, 10, 12),
        date(2026, 11, 3),
        date(2026, 11, 23),
        date(2026, 12, 31),
        date(2027, 1, 1),
        date(2027, 1, 2),
        date(2027, 1, 3),
        date(2027, 1, 11),
        date(2027, 2, 11),
        date(2027, 2, 23),
        date(2027, 3, 21),
        date(2027, 3, 22),
        date(2027, 4, 29),
        date(2027, 5, 3),
        date(2027, 5, 4),
        date(2027, 5, 5),
        date(2027, 7, 19),
        date(2027, 8, 11),
        date(2027, 9, 20),
        date(2027, 9, 23),
        date(2027, 10, 11),
        date(2027, 11, 3),
        date(2027, 11, 23),
        date(2027, 12, 31),
    }
)


@dataclass(frozen=True)
class VerifiedMarketSessionResult:
    allowed: bool
    reason: str
    venue: str
    local_timestamp: str
    session: str


def _minute_of_day(value: datetime) -> float:
    return value.hour * 60 + value.minute + value.second / 60 + value.microsecond / 60_000_000


def _result(*, allowed: bool, reason: str, venue: str, local: datetime, session: str) -> VerifiedMarketSessionResult:
    return VerifiedMarketSessionResult(
        allowed=bool(allowed),
        reason=str(reason),
        venue=venue,
        local_timestamp=local.isoformat(timespec="seconds"),
        session=session,
    )


def evaluate_verified_market_session(
    ticker: str,
    *,
    now: datetime | None = None,
) -> VerifiedMarketSessionResult:
    """Permit a verified Paper order only during an audited regular/core session."""
    normalized = str(ticker).strip().upper()
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        # A naive clock can be interpreted in multiple time zones, so never guess.
        local = current.replace(tzinfo=timezone.utc)
        return _result(
            allowed=False,
            reason="market session blocked because current time is timezone-naive",
            venue="UNKNOWN",
            local=local,
            session="UNVERIFIED",
        )

    if normalized in _VERIFIED_US_EQUITIES:
        local = current.astimezone(_US_ZONE)
        venue = "US_CORE"
        if local.year not in _SUPPORTED_YEARS:
            return _result(
                allowed=False,
                reason=f"US exchange calendar year {local.year} is not audited",
                venue=venue,
                local=local,
                session="UNSUPPORTED_CALENDAR_YEAR",
            )
        if local.weekday() >= 5:
            return _result(
                allowed=False,
                reason="US core session is closed on weekends",
                venue=venue,
                local=local,
                session="CLOSED_WEEKEND",
            )
        if local.date() in _US_HOLIDAYS:
            return _result(
                allowed=False,
                reason="US core session is closed for an exchange holiday",
                venue=venue,
                local=local,
                session="CLOSED_HOLIDAY",
            )
        minute = _minute_of_day(local)
        close_minute = 13 * 60 if local.date() in _US_EARLY_CLOSES else 16 * 60
        if 9 * 60 + 30 <= minute < close_minute:
            return _result(
                allowed=True,
                reason="US core session is open",
                venue=venue,
                local=local,
                session="CORE_OPEN",
            )
        return _result(
            allowed=False,
            reason="US verified Paper orders are allowed only during the core session",
            venue=venue,
            local=local,
            session="CLOSED_OUTSIDE_CORE",
        )

    if normalized.endswith(".T"):
        local = current.astimezone(_JPX_ZONE)
        venue = "TSE_CASH"
        if local.year not in _SUPPORTED_YEARS:
            return _result(
                allowed=False,
                reason=f"JPX cash-market calendar year {local.year} is not audited",
                venue=venue,
                local=local,
                session="UNSUPPORTED_CALENDAR_YEAR",
            )
        if local.weekday() >= 5:
            return _result(
                allowed=False,
                reason="TSE cash market is closed on weekends",
                venue=venue,
                local=local,
                session="CLOSED_WEEKEND",
            )
        if local.date() in _JPX_HOLIDAYS:
            return _result(
                allowed=False,
                reason="TSE cash market is closed for an exchange holiday",
                venue=venue,
                local=local,
                session="CLOSED_HOLIDAY",
            )
        minute = _minute_of_day(local)
        morning_open = 9 * 60 <= minute < 11 * 60 + 30
        afternoon_open = 12 * 60 + 30 <= minute < 15 * 60 + 30
        if morning_open:
            return _result(
                allowed=True,
                reason="TSE morning auction session is open",
                venue=venue,
                local=local,
                session="MORNING_OPEN",
            )
        if afternoon_open:
            return _result(
                allowed=True,
                reason="TSE afternoon auction session is open",
                venue=venue,
                local=local,
                session="AFTERNOON_OPEN",
            )
        return _result(
            allowed=False,
            reason="TSE verified Paper orders are allowed only during auction sessions",
            venue=venue,
            local=local,
            session="CLOSED_OUTSIDE_AUCTION",
        )

    local = current.astimezone(timezone.utc)
    return _result(
        allowed=False,
        reason=f"market session policy is not registered for {normalized or 'EMPTY'}",
        venue="UNSUPPORTED",
        local=local,
        session="UNSUPPORTED_SYMBOL",
    )
