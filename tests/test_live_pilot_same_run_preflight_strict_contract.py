from ai_asset_platform.brokers.ibkr_live_all_open_orders import REPORT_SCHEMA_VERSION
from ai_asset_platform.execution.live_pilot_same_run_preflight import (
    _paper_safe,
    _read_only_clean,
)


def _open_orders_report() -> dict:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "ready": True,
        "connection_mode": "LIVE_READ_ONLY",
        "order_sent": False,
        "cancel_sent": False,
        "live_order_sent": False,
    }


def test_same_run_open_orders_requires_every_transport_flag_exact_false():
    required = ("order_sent", "cancel_sent", "live_order_sent")
    assert _read_only_clean(
        _open_orders_report(),
        required_schema_version=REPORT_SCHEMA_VERSION,
        required_false_flags=required,
    ) is True

    for flag in required:
        missing = _open_orders_report()
        missing.pop(flag)
        assert _read_only_clean(
            missing,
            required_schema_version=REPORT_SCHEMA_VERSION,
            required_false_flags=required,
        ) is False

        for falsey_but_not_false in (None, 0, ""):
            malformed = _open_orders_report()
            malformed[flag] = falsey_but_not_false
            assert _read_only_clean(
                malformed,
                required_schema_version=REPORT_SCHEMA_VERSION,
                required_false_flags=required,
            ) is False


def test_same_run_read_only_clean_rejects_non_exact_int_schema_version():
    for malformed in (float(REPORT_SCHEMA_VERSION), str(REPORT_SCHEMA_VERSION), True):
        report = _open_orders_report()
        report["schema_version"] = malformed
        assert _read_only_clean(
            report,
            required_schema_version=REPORT_SCHEMA_VERSION,
        ) is False


def _paper_report(**overrides) -> dict:
    data = {
        "schema_version": 1,
        "status": "HEALTHY",
        "accounting_safe": True,
        "risk_safe": True,
        "monitor_order_sent": False,
        "live_order_sent": False,
        "broker": {
            "account_ready": True,
            "execution_snapshot_ready": True,
            "all_open_orders_ready": True,
            "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
            "reconciliation_blocker_count": 0,
            "open_order_count": 0,
            "open_orders": [],
            "endpoint_port": 4002,
        },
    }
    data.update(overrides)
    return data


def test_same_run_paper_safe_requires_exact_healthy_schema_current_snapshot():
    assert _paper_safe(_paper_report()) is True
    assert _paper_safe(_paper_report(schema_version=0)) is False


def test_same_run_paper_safe_rejects_non_exact_int_schema_version():
    for malformed in (1.0, "1", True):
        assert _paper_safe(_paper_report(schema_version=malformed)) is False
