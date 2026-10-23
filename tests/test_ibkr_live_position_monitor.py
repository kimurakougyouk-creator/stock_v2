from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

import ai_asset_platform.brokers.ibkr_live_position_monitor as module
from ai_asset_platform.brokers.ibkr_live_position_monitor import audit_live_snapshots

NOW = datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)
FP = "a" * 64


def snapshots():
    core = dict(
        checked_at=NOW.isoformat(), connection_mode="LIVE_READ_ONLY",
        endpoint_port=7496, account_fingerprint=FP,
        connected=True, ready=True, order_sent=False, live_order_sent=False,
    )
    account = {**core, "positions": [{"symbol": "9432", "quantity": 100, "sec_type": "STK", "currency": "JPY", "exchange": "TSEJ"}]}
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


def test_wrong_instrument_fails_closed():
    a, o = snapshots()
    a["positions"][0]["sec_type"] = "OPT"
    a["positions"][0]["currency"] = "USD"
    assert "INSTRUMENT_MISMATCH" in audit(a, o)["alert_codes"]


def test_non_object_evidence_rejected():
    a, o = snapshots()
    with pytest.raises(ValueError, match="snapshots must be objects"):
        audit_live_snapshots(None, o, expected_fingerprint=FP,
            expected_positions={"9432": 100}, now=NOW)


def test_ancient_checked_at_fails_closed_not_crash():
    # Regression: Codex P3 (HEAD 24cd8bd). `datetime.astimezone(timezone.utc)`
    # on an out-of-range date raised an uncaught OverflowError instead of the
    # STALE_EVIDENCE alert the freshness check is meant to produce.
    a, o = snapshots()
    a["checked_at"] = "0001-01-01T00:00:00+01:00"
    assert "STALE_EVIDENCE" in audit(a, o)["alert_codes"]


def test_overflowing_quantity_fails_closed_not_crash():
    # Regression: Codex P3 (HEAD 24cd8bd). float() on a too-large int
    # (e.g. a corrupted or adversarial position quantity) raised an
    # uncaught OverflowError instead of the INVALID_POSITIONS alert.
    a, o = snapshots()
    a["positions"][0]["quantity"] = 10**400
    assert "INVALID_POSITIONS" in audit(a, o)["alert_codes"]


def test_cli_rejects_overflowing_evidence_without_crashing(tmp_path, monkeypatch):
    # Same Codex P3 finding, exercised at the CLI boundary (main()), where
    # an uncaught OverflowError would previously surface as a bare
    # traceback and exit code 1 instead of the structured JSON alert
    # contract every other malformed-evidence path already honors.
    a, o = snapshots()
    a["checked_at"] = "0001-01-01T00:00:00+01:00"
    account_path = tmp_path / "account.json"
    orders_path = tmp_path / "orders.json"
    import json

    account_path.write_text(json.dumps(a), encoding="utf-8")
    orders_path.write_text(json.dumps(o), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "ibkr_live_position_monitor",
            "--account-snapshot", str(account_path),
            "--orders-snapshot", str(orders_path),
            "--expected-fingerprint", FP,
        ],
    )

    exit_code = module.main()

    assert exit_code == 1


def test_fresh_entrypoint_reuses_existing_acquisition_and_persist_functions(
    monkeypatch, tmp_path
):
    # Covers item 3 of the follow-up: a non-order entry point that acquires
    # FRESH Live Read-Only evidence (never reads stale files first) by
    # reusing the existing acquisition/persist functions verbatim, then
    # judges it with the same audit_live_snapshots used by the offline path.
    account_report_path = tmp_path / "account.json"
    orders_report_path = tmp_path / "orders.json"
    calls = []

    def fake_preview_account(*, confirmation=None):
        calls.append(("account", confirmation))
        return object()

    def fake_persist_account(snapshot, *, report_path):
        a, _ = snapshots()
        report_path.write_text(__import__("json").dumps(a), encoding="utf-8")

    def fake_preview_orders(*, confirmation=None):
        calls.append(("orders", confirmation))
        return object()

    def fake_persist_orders(snapshot, *, report_path):
        _, o = snapshots()
        report_path.write_text(__import__("json").dumps(o), encoding="utf-8")

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_live_readonly_account.preview_ibkr_live_readonly_account_snapshot",
        fake_preview_account,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_live_readonly_account.persist_live_readonly_account_snapshot",
        fake_persist_account,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_live_all_open_orders.preview_ibkr_live_all_open_orders",
        fake_preview_orders,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_live_all_open_orders.persist_live_all_open_orders",
        fake_persist_orders,
    )

    # Freeze the audit clock to match the fixture timestamps at any CI run date.
    class FixedDateTime(datetime):
        @staticmethod
        def now(tz):
            return NOW
    monkeypatch.setattr(module, "datetime", FixedDateTime)

    result = module.run_live_position_monitor_once(
        expected_fingerprint=FP,
        expected_symbol="9432",
        expected_quantity=100,
        confirmation="READ_LIVE_ACCOUNT_ONLY",
        account_report_path=account_report_path,
        orders_report_path=orders_report_path,
    )

    assert result["status"] == "OK"
    assert ("account", "READ_LIVE_ACCOUNT_ONLY") in calls
    assert ("orders", "READ_LIVE_ACCOUNT_ONLY") in calls
    assert result["order_sent"] is False
    assert result["live_order_sent"] is False


def test_fresh_entrypoint_fails_closed_when_acquisition_is_blocked(
    monkeypatch, tmp_path
):
    # Non-order mock: confirmation missing / broker unreachable must still
    # fail closed to ALERT, never silently report OK.
    account_report_path = tmp_path / "account.json"
    orders_report_path = tmp_path / "orders.json"

    def fake_persist(snapshot, *, report_path):
        report_path.write_text(
            __import__("json").dumps(
                {
                    "connection_mode": "LIVE_READ_ONLY",
                    "checked_at": NOW.isoformat(),
                    "endpoint_port": None,
                    "account_fingerprint": None,
                    "connected": False,
                    "ready": False,
                    "order_sent": False,
                    "live_order_sent": False,
                    "positions": [],
                    "orders": [],
                    "open_order_count": 0,
                    "cancel_sent": False,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_live_readonly_account.preview_ibkr_live_readonly_account_snapshot",
        lambda *, confirmation=None: object(),
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_live_readonly_account.persist_live_readonly_account_snapshot",
        fake_persist,
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_live_all_open_orders.preview_ibkr_live_all_open_orders",
        lambda *, confirmation=None: object(),
    )
    monkeypatch.setattr(
        "ai_asset_platform.brokers.ibkr_live_all_open_orders.persist_live_all_open_orders",
        fake_persist,
    )

    result = module.run_live_position_monitor_once(
        expected_fingerprint=FP,
        account_report_path=account_report_path,
        orders_report_path=orders_report_path,
    )

    assert result["status"] == "ALERT"
    assert "BROKER_UNAVAILABLE" in result["alert_codes"]


def test_module_contains_no_order_mutation_api():
    source = Path(
        "src/ai_asset_platform/brokers/ibkr_live_position_monitor.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "whatIf=True",
        "transmit_ibkr",
        "enable_live_trading = True",
    )
    for token in forbidden:
        assert token not in source
