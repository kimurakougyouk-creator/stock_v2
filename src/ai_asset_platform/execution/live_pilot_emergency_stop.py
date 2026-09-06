"""Independent emergency-stop latch for the first Live pilot.

The future Live sender must check :func:`live_pilot_stop_is_active` immediately
before any broker order API call.  This module itself contains no broker API and
cannot send, cancel, modify, retry, flatten, or close an order.

Two stop sources are deliberately combined:
- the existing immutable PlatformSettings.emergency_stop flag; and
- a durable local stop file that can be asserted independently at runtime.

A stop is easy to assert and deliberately harder to clear.  Clearing the local
latch requires an exact operator phrase; clearing never changes PlatformSettings.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from ai_asset_platform.core.settings import SETTINGS, PlatformSettings


DEFAULT_STOP_PATH = Path("results/live_pilot_emergency_stop.json")
CLEAR_CONFIRMATION_VALUE = "CLEAR_ONE_LIVE_PILOT_STOP_ONLY"
REPORT_SCHEMA_VERSION = 1


def _aware_utc(value: datetime | None) -> datetime:
    current = value if value is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("emergency-stop clock must be timezone-aware")
    return current.astimezone(timezone.utc)


def request_live_pilot_stop(
    reason: str,
    *,
    stop_path: Path = DEFAULT_STOP_PATH,
    now: datetime | None = None,
) -> None:
    """Assert the durable stop latch. Repeated requests leave it asserted."""
    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValueError("stop reason is required")
    current = _aware_utc(now)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "STOP_REQUESTED",
        "stop_requested": True,
        "reason": normalized_reason,
        "checked_at": current.isoformat(timespec="seconds"),
        "order_sent": False,
        "live_order_sent": False,
    }
    stop_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = stop_path.with_suffix(stop_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, stop_path)


def clear_local_live_pilot_stop(
    *,
    confirmation: str,
    stop_path: Path = DEFAULT_STOP_PATH,
) -> bool:
    """Clear only the local latch after exact operator confirmation.

    Returns True when a local stop file was removed.  The global settings-level
    emergency stop is intentionally untouched and may still keep the pilot
    stopped.
    """
    if str(confirmation or "").strip() != CLEAR_CONFIRMATION_VALUE:
        raise PermissionError("exact emergency-stop clear confirmation is missing")
    try:
        stop_path.unlink()
    except FileNotFoundError:
        return False
    return True


def live_pilot_stop_is_active(
    *,
    settings: PlatformSettings = SETTINGS,
    stop_path: Path = DEFAULT_STOP_PATH,
) -> bool:
    """Return True whenever either independent emergency-stop source is active."""
    return bool(settings.emergency_stop or stop_path.exists())


def emergency_stop_record(
    *,
    settings: PlatformSettings = SETTINGS,
    stop_path: Path = DEFAULT_STOP_PATH,
    now: datetime | None = None,
) -> dict:
    current = _aware_utc(now)
    local_stop = stop_path.exists()
    global_stop = bool(settings.emergency_stop)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "checked_at": current.isoformat(timespec="seconds"),
        "status": "STOPPED" if (local_stop or global_stop) else "CLEAR",
        "global_emergency_stop": global_stop,
        "local_emergency_stop": local_stop,
        "stop_active": bool(local_stop or global_stop),
        "order_sent": False,
        "live_order_sent": False,
    }
