from ai_asset_platform.brokers.ibkr_live_all_open_orders import REPORT_SCHEMA_VERSION
from ai_asset_platform.execution.live_pilot_same_run_preflight import _read_only_clean


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
