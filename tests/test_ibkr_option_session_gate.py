from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from ai_asset_platform.brokers import ibkr_option_session_gate as gate


def test_liquid_hours_open_inside_exact_broker_window():
    result = gate.evaluate_liquid_hours(
        time_zone_id="US/Eastern",
        liquid_hours="20260825:0930-20260825:1615;20260826:0930-20260826:1615",
        now=datetime(2026, 8, 25, 10, 0, tzinfo=ZoneInfo("US/Eastern")),
    )
    assert result.resolved is True
    assert result.open_now is True
    assert result.ready is True
    assert result.matching_window == "20260825:0930-20260825:1615"


def test_liquid_hours_closed_before_session():
    result = gate.evaluate_liquid_hours(
        time_zone_id="US/Eastern",
        liquid_hours="20260825:0930-20260825:1615",
        now=datetime(2026, 8, 25, 9, 29, tzinfo=ZoneInfo("US/Eastern")),
    )
    assert result.resolved is True
    assert result.open_now is False
    assert result.ready is False


def test_closed_day_never_opens():
    result = gate.evaluate_liquid_hours(
        time_zone_id="US/Eastern",
        liquid_hours="20260825:CLOSED;20260826:0930-20260826:1615",
        now=datetime(2026, 8, 25, 12, 0, tzinfo=ZoneInfo("US/Eastern")),
    )
    assert result.open_now is False


def test_incomplete_metadata_fails_closed():
    result = gate.evaluate_liquid_hours(time_zone_id=None, liquid_hours=None)
    assert result.resolved is False
    assert result.ready is False
    assert result.errors


def test_runtime_live_lock_blocks_before_discovery(monkeypatch):
    monkeypatch.setattr(
        gate,
        "SETTINGS",
        SimpleNamespace(
            enable_ibkr_paper=True,
            enable_live_trading=True,
            live_trading_unlocked=True,
        ),
    )
    monkeypatch.setattr(
        gate,
        "_verified_target",
        lambda: (_ for _ in ()).throw(AssertionError("discovery must not run")),
    )
    result = gate.run_option_session_gate()
    assert result.ready is False
    assert "Live Trading safety lock" in result.errors[0]
    assert result.real_order_sent is False
    assert result.live_order_sent is False
