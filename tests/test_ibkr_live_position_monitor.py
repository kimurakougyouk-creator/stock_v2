from datetime import datetime, timezone, timedelta

from ai_asset_platform.brokers.ibkr_live_position_monitor import audit_live_snapshots

NOW = datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)
FP = "a" * 64


def snapshots():
    core = dict(
        checked_at=NOW.isoformat(), connection_mode="LIVE_READ_ONLY",
        endpoint_port=7496, account_fingerprint=FP,
        connected=True, ready=True, order_sent=False, live_order_sent=False,
    )
    account = {**core, "positions": [{"symbol": "9432", "quantity": 100}]}
    orders = {**core, "orders": [], "open_order_count": 0, "cancel_sent": False}
    return account, orders


def audit(a, o):
    return audit_live_snapshots(a, o, expected_fingerprint=FP,
        expected_positions={"9432": 100}, now=NOW)


def test_clean_evidence():
    a, o = snapshots()
    assert audit(a, o)["status"] == "OK"


def test_stale_evidence_fails_closed():
    a, o = snapshots()
    a["checked_at"] = (NOW - timedelta(hours=1)).isoformat()
    assert "STALE_EVIDENCE" in audit(a, o)["alert_codes"]


def test_mismatched_position_and_open_order():
    a, o = snapshots()
    a["positions"][0]["quantity"] = 99
    o["orders"] = [{"opaque": "not-persisted-in-alert"}]
    result = audit(a, o)
    assert "POSITION_MISMATCH" in result["alert_codes"]
    assert "UNEXPECTED_OPEN_ORDERS" in result["alert_codes"]
    assert "opaque" not in str(result)


def test_account_or_connection_error():
    a, o = snapshots()
    o["account_fingerprint"] = "b" * 64
    a["connected"] = False
    codes = audit(a, o)["alert_codes"]
    assert "ACCOUNT_MISMATCH" in codes
    assert "BROKER_UNAVAILABLE" in codes


def test_reject_paper_and_write_flags():
    a, o = snapshots()
    a["connection_mode"] = "PAPER"
    o["cancel_sent"] = True
    codes = audit(a, o)["alert_codes"]
    assert "INVALID_SOURCE" in codes
    assert "UNEXPECTED_WRITE_FLAG" in codes
