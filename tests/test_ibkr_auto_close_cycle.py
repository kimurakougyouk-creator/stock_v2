from datetime import datetime
from zoneinfo import ZoneInfo

import ai_asset_platform.brokers.ibkr_auto_close_cycle as module

ET = ZoneInfo("America/New_York")


def test_auto_close_selects_extended_after_hours():
    route = module.choose_close_route(datetime(2026, 8, 21, 16, 30, tzinfo=ET))
    assert route == "EXTENDED_RTH"


def test_auto_close_selects_overnight_when_open():
    route = module.choose_close_route(datetime(2026, 8, 20, 21, 0, tzinfo=ET))
    assert route == "OVERNIGHT"


def test_auto_close_has_no_route_on_weekend():
    route = module.choose_close_route(datetime(2026, 8, 22, 16, 30, tzinfo=ET))
    assert route is None
