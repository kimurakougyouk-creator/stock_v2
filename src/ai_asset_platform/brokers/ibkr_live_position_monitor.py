"""Offline, fail-closed monitor of independently collected Live read-only snapshots.

This module NEVER connects to IBKR and NEVER places/cancels orders. It reads
existing reports only. Scheduling and notifications are intentionally separate,
operator-approved follow-up work.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path


def _fresh(snapshot: dict, now: datetime, max_age_seconds: int) -> bool:
    try:
        stamp = datetime.fromisoformat(snapshot["checked_at"])
        if stamp.tzinfo is None:
            return False
        age = (now - stamp.astimezone(timezone.utc)).total_seconds()
        return 0 <= age <= max_age_seconds
    except (KeyError, TypeError, ValueError):
        return False


def audit_live_snapshots(
    account: dict,
    orders: dict,
    *,
    expected_fingerprint: str,
    expected_positions: dict[str, float],
    now: datetime,
    max_age_seconds: int = 900,
) -> dict:
    """Use fixed alert codes, not raw broker errors or private account IDs."""
    alerts: set[str] = set()
    if not expected_fingerprint or len(expected_fingerprint) != 64:
        raise ValueError("expected_fingerprint must be a SHA-256 hex digest")
    if any(c not in "0123456789abcdef" for c in expected_fingerprint.lower()):
        raise ValueError("invalid expected_fingerprint")
    if max_age_seconds <= 0 or now.tzinfo is None:
        raise ValueError("invalid time settings")
    if not isinstance(account, dict) or not isinstance(orders, dict):
        raise ValueError("snapshots must be objects")
    if not isinstance(expected_positions, dict) or not expected_positions:
        raise ValueError("explicit expected positions required")

    for item in (account, orders):
        if item.get("connection_mode") != "LIVE_READ_ONLY":
            alerts.add("INVALID_SOURCE")
        if not _fresh(item, now, max_age_seconds):
            alerts.add("STALE_EVIDENCE")
        if item.get("endpoint_port") not in (4001, 7496):
            alerts.add("INVALID_ENDPOINT")
        if item.get("account_fingerprint") != expected_fingerprint:
            alerts.add("ACCOUNT_MISMATCH")
        if item.get("order_sent") is not False or item.get("live_order_sent") is not False:
            alerts.add("UNEXPECTED_WRITE_FLAG")
        if item.get("ready") is not True or item.get("connected") is not True:
            alerts.add("BROKER_UNAVAILABLE")
    if account.get("endpoint_port") != orders.get("endpoint_port"):
        alerts.add("SESSION_MISMATCH")
    if orders.get("cancel_sent") is not False:
        alerts.add("UNEXPECTED_WRITE_FLAG")

    positions = account.get("positions")
    observed: dict[str, float] = {}
    if not isinstance(positions, list):
        alerts.add("INVALID_POSITIONS")
    else:
        for position in positions:
            try:
                symbol = position["symbol"]
                qty = float(position["quantity"])
                if not isinstance(symbol, str) or not symbol or not math.isfinite(qty):
                    raise ValueError
                if symbol in observed:
                    raise ValueError
                if position.get("sec_type") != "STK" or position.get("currency") != "JPY":
                    alerts.add("INSTRUMENT_MISMATCH")
                observed[symbol] = qty
            except (KeyError, TypeError, ValueError):
                alerts.add("INVALID_POSITIONS")
    for symbol, quantity in expected_positions.items():
        if not isinstance(symbol, str) or not math.isfinite(float(quantity)):
            raise ValueError("invalid expected position")
    if observed != {k: float(v) for k, v in expected_positions.items()}:
        alerts.add("POSITION_MISMATCH")

    open_orders = orders.get("orders")
    if not isinstance(open_orders, list) or len(open_orders) != 0:
        alerts.add("UNEXPECTED_OPEN_ORDERS")
    if orders.get("open_order_count") != 0:
        alerts.add("UNEXPECTED_OPEN_ORDERS")
    return {
        "status": "ALERT" if alerts else "OK",
        "alert_codes": sorted(alerts),
        "checked_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "account_fingerprint_verified": "ACCOUNT_MISMATCH" not in alerts,
        "order_sent": False,
        "live_order_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Live read-only snapshot audit")
    parser.add_argument("--account-snapshot", type=Path, default=Path("results/ibkr_live_readonly_account_latest.json"))
    parser.add_argument("--orders-snapshot", type=Path, default=Path("results/ibkr_live_all_open_orders_latest.json"))
    parser.add_argument("--expected-fingerprint", required=True, help="SHA-256 fingerprint, never raw account ID")
    parser.add_argument("--expected-symbol", default="9432")
    parser.add_argument("--expected-quantity", type=float, default=100)
    parser.add_argument("--max-age-seconds", type=int, default=900)
    args = parser.parse_args()
    try:
        account = json.loads(args.account_snapshot.read_text(encoding="utf-8"))
        orders = json.loads(args.orders_snapshot.read_text(encoding="utf-8"))
        result = audit_live_snapshots(account, orders,
            expected_fingerprint=args.expected_fingerprint,
            expected_positions={args.expected_symbol: args.expected_quantity},
            now=datetime.now(timezone.utc), max_age_seconds=args.max_age_seconds)
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        result = {"status": "ALERT", "alert_codes": ["INVALID_OR_MISSING_EVIDENCE"],
                  "order_sent": False, "live_order_sent": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
