from dataclasses import replace

from ai_asset_platform.core.account_clock import account_now, account_zone
from ai_asset_platform.core.settings import SETTINGS


def test_default_account_timezone_is_tokyo():
    assert SETTINGS.account_timezone == "Asia/Tokyo"
    assert account_zone(SETTINGS).key == "Asia/Tokyo"


def test_account_now_is_timezone_aware():
    value = account_now(SETTINGS)
    assert value.tzinfo is not None
    assert getattr(value.tzinfo, "key", None) == "Asia/Tokyo"


def test_clock_can_follow_an_explicit_other_account_timezone():
    settings = replace(SETTINGS, account_timezone="America/New_York")
    assert account_zone(settings).key == "America/New_York"
    assert getattr(account_now(settings).tzinfo, "key", None) == "America/New_York"
