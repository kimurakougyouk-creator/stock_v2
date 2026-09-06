from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_asset_platform.core.settings import PlatformSettings
from ai_asset_platform.execution.live_pilot_emergency_stop import (
    CLEAR_CONFIRMATION_VALUE,
    clear_local_live_pilot_stop,
    emergency_stop_record,
    live_pilot_stop_is_active,
    request_live_pilot_stop,
)


NOW = datetime(2026, 9, 6, 7, 0, 0, tzinfo=timezone.utc)


def test_local_stop_can_be_asserted_without_broker_action(tmp_path: Path):
    stop_path = tmp_path / "stop.json"
    settings = PlatformSettings(emergency_stop=False)

    assert live_pilot_stop_is_active(settings=settings, stop_path=stop_path) is False
    request_live_pilot_stop("operator requested stop", stop_path=stop_path, now=NOW)
    assert live_pilot_stop_is_active(settings=settings, stop_path=stop_path) is True

    record = emergency_stop_record(settings=settings, stop_path=stop_path, now=NOW)
    assert record["status"] == "STOPPED"
    assert record["local_emergency_stop"] is True
    assert record["order_sent"] is False
    assert record["live_order_sent"] is False


def test_global_stop_cannot_be_cleared_by_local_clear(tmp_path: Path):
    stop_path = tmp_path / "stop.json"
    settings = PlatformSettings(emergency_stop=True)
    request_live_pilot_stop("both stops active", stop_path=stop_path, now=NOW)

    assert clear_local_live_pilot_stop(
        confirmation=CLEAR_CONFIRMATION_VALUE,
        stop_path=stop_path,
    ) is True
    assert live_pilot_stop_is_active(settings=settings, stop_path=stop_path) is True


def test_local_stop_clear_requires_exact_confirmation(tmp_path: Path):
    stop_path = tmp_path / "stop.json"
    request_live_pilot_stop("stop", stop_path=stop_path, now=NOW)

    with pytest.raises(PermissionError, match="clear confirmation"):
        clear_local_live_pilot_stop(confirmation="yes", stop_path=stop_path)
    assert stop_path.exists()


def test_local_stop_clear_is_explicit_and_idempotent(tmp_path: Path):
    stop_path = tmp_path / "stop.json"
    request_live_pilot_stop("stop", stop_path=stop_path, now=NOW)

    assert clear_local_live_pilot_stop(
        confirmation=CLEAR_CONFIRMATION_VALUE,
        stop_path=stop_path,
    ) is True
    assert clear_local_live_pilot_stop(
        confirmation=CLEAR_CONFIRMATION_VALUE,
        stop_path=stop_path,
    ) is False


def test_module_contains_no_order_transport():
    source = Path(
        "src/ai_asset_platform/execution/live_pilot_emergency_stop.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "reqOpenOrders(",
        "reqAllOpenOrders(",
        "enable_live_trading = True",
        "whatIf=True",
    )
    for token in forbidden:
        assert token not in source
