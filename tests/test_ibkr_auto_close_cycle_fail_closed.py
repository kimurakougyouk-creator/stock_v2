from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import ai_asset_platform.brokers.ibkr_auto_close_cycle as module

ET = ZoneInfo("America/New_York")


def test_no_supported_session_never_calls_a_close_route(monkeypatch):
    snapshot = SimpleNamespace(
        ready=True,
        positions=(SimpleNamespace(symbol="SPY", sec_type="STK", quantity=1.0, market_price=760.0),),
    )
    monkeypatch.setattr(module, "preview_ibkr_paper_account_snapshot", lambda: snapshot)
    called = {"overnight": False, "extended": False}

    def _overnight(**kwargs):
        called["overnight"] = True
        raise AssertionError("overnight close should not be called")

    def _extended(**kwargs):
        called["extended"] = True
        raise AssertionError("extended close should not be called")

    monkeypatch.setattr(module, "run_spy_overnight_paper_close", _overnight)
    monkeypatch.setattr(module, "run_spy_extended_paper_close", _extended)

    result = module.run_auto_close_cycle(datetime(2026, 8, 22, 16, 30, tzinfo=ET))
    assert result.route is None
    assert result.close_result is None
    assert called == {"overnight": False, "extended": False}
