from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_asset_platform.core.settings import PlatformSettings
from ai_asset_platform.execution.live_pilot_emergency_stop import request_live_pilot_stop
from ai_asset_platform.execution.live_pilot_same_run_preflight import (
    evaluate_live_pilot_same_run_preflight,
)


NOW = datetime(2026, 9, 6, 7, 30, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64


def _stamp(offset_seconds: int = 0) -> str:
    return (NOW + timedelta(seconds=offset_seconds)).isoformat(timespec="seconds")


def _readiness(**overrides) -> dict:
    data = {
        "status": "READY_FOR_ONE_OPERATIONAL_PILOT",
        "checked_at": _stamp(),
        "ticker": "AAPL",
        "quantity": 1,
        "limit_price": 250.0,
        "estimated_notional_jpy": 37_500.0,
        "operational_pilot_ready": True,
        "live_global_lock_intact_during_preparation": True,
        "order_sent": False,
        "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _account(**overrides) -> dict:
    data = {
        "ready": True,
        "checked_at": _stamp(),
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "available_funds": 100_000.0,
        "settled_cash_by_currency": {"USD": 1_000.0, "JPY": 100_000.0},
        "order_sent": False,
        "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _open_orders(**overrides) -> dict:
    data = {
        "ready": True,
        "checked_at": _stamp(),
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "open_order_count": 0,
        "order_sent": False,
        "cancel_sent": False,
        "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _fx(**overrides) -> dict:
    data = {
        "ready": True,
        "checked_at": _stamp(),
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "base_currency": "USD",
        "quote_currency": "JPY",
        "rate": 150.0,
        "order_sent": False,
        "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _paper(**overrides) -> dict:
    data = {
        "status": "WARNING",
        "checked_at": _stamp(),
        "accounting_safe": True,
        "risk_safe": True,
        "monitor_order_sent": False,
        "live_order_sent": False,
        "broker": {
            "reconciliation_blocker_count": 0,
            "open_order_count": 0,
        },
    }
    data.update(overrides)
    return data


def _evaluate(tmp_path: Path, **overrides):
    params = {
        "ticker": "AAPL",
        "expected_account_fingerprint": FINGERPRINT,
        "readiness_report": _readiness(),
        "live_account_report": _account(),
        "live_open_orders_report": _open_orders(),
        "live_fx_report": _fx(),
        "paper_monitor_report": _paper(),
        "settings": PlatformSettings(),
        "stop_path": tmp_path / "live-stop.json",
        "now": NOW,
    }
    params.update(overrides)
    return evaluate_live_pilot_same_run_preflight(**params)


def test_clean_same_run_evidence_is_ready_only_for_operator_authorization(tmp_path: Path):
    result = _evaluate(tmp_path)

    assert result.ready is True
    assert result.status == "READY_FOR_OPERATOR_AUTHORIZATION"
    assert result.endpoint_port == 4001
    assert result.endpoint_binding_ready is True
    assert result.account_fingerprint_match is True
    assert result.evidence_fresh is True
    assert result.available_funds_ready is True
    assert result.settled_cash_currency == "USD"
    assert result.settled_cash_ready is True
    assert result.order_sent is False
    assert result.live_order_sent is False


def test_missing_or_insufficient_available_funds_fail_closed(tmp_path: Path):
    missing = _evaluate(tmp_path, live_account_report=_account(available_funds=None))
    assert missing.ready is False
    assert missing.available_funds_ready is False

    insufficient = _evaluate(tmp_path, live_account_report=_account(available_funds=38_000.0))
    assert insufficient.ready is False
    assert insufficient.required_available_funds_jpy == 38_500.0
    assert any("available funds" in item for item in insufficient.blockers)


def test_missing_or_insufficient_settled_instrument_cash_fail_closed(tmp_path: Path):
    missing = _evaluate(
        tmp_path,
        live_account_report=_account(settled_cash_by_currency={"JPY": 100_000.0}),
    )
    assert missing.ready is False
    assert missing.settled_cash_ready is False

    insufficient = _evaluate(
        tmp_path,
        live_account_report=_account(settled_cash_by_currency={"USD": 259.99}),
    )
    assert insufficient.ready is False
    assert insufficient.required_settled_cash_amount == 260.0
    assert any("settled USD cash" in item for item in insufficient.blockers)


def test_mixed_live_endpoints_fail_closed(tmp_path: Path):
    result = _evaluate(
        tmp_path,
        live_open_orders_report=_open_orders(endpoint_port=7496),
    )

    assert result.ready is False
    assert result.endpoint_binding_ready is False
    assert any("mixed across different endpoints" in item for item in result.blockers)


def test_usd_fx_must_come_from_same_live_endpoint(tmp_path: Path):
    result = _evaluate(tmp_path, live_fx_report=_fx(endpoint_port=7496))

    assert result.ready is False
    assert result.endpoint_binding_ready is False


def test_stale_evidence_fails_same_run_window(tmp_path: Path):
    result = _evaluate(
        tmp_path,
        live_account_report=_account(checked_at=_stamp(-31)),
    )

    assert result.ready is False
    assert result.evidence_fresh is False
    assert any("account evidence is outside" in item for item in result.blockers)


def test_evidence_skew_is_bounded_even_when_each_report_is_fresh(tmp_path: Path):
    result = _evaluate(
        tmp_path,
        live_account_report=_account(checked_at=_stamp(-20)),
    )

    assert result.ready is False
    assert result.evidence_fresh is True
    assert result.evidence_skew_seconds == 20.0
    assert "same-run evidence timestamps are too far apart" in result.blockers


def test_wrong_pinned_account_fails_closed(tmp_path: Path):
    result = _evaluate(tmp_path, expected_account_fingerprint="b" * 64)

    assert result.ready is False
    assert result.account_fingerprint_match is False


def test_unexpected_open_live_order_fails_closed(tmp_path: Path):
    result = _evaluate(
        tmp_path,
        live_open_orders_report=_open_orders(open_order_count=1),
    )

    assert result.ready is False
    assert "same-run Live open-order evidence is not empty" in result.blockers


def test_emergency_stop_is_checked_in_final_read_only_gate(tmp_path: Path):
    stop_path = tmp_path / "live-stop.json"
    request_live_pilot_stop("test stop", stop_path=stop_path, now=NOW)

    result = _evaluate(tmp_path, stop_path=stop_path)

    assert result.ready is False
    assert result.emergency_stop_clear is False
    assert "Live pilot emergency stop is active" in result.blockers


def test_global_live_unlock_during_preparation_fails_closed(tmp_path: Path):
    settings = PlatformSettings(
        run_mode="LIVE",
        enable_live_trading=True,
        enable_paper_trading=False,
    )
    result = _evaluate(tmp_path, settings=settings)

    assert result.ready is False
    assert result.live_global_lock_intact is False


def test_jpy_pilot_requires_settled_jpy_cash_plus_reserve(tmp_path: Path):
    result = _evaluate(
        tmp_path,
        ticker="9432.T",
        readiness_report=_readiness(
            ticker="9432.T",
            quantity=100,
            limit_price=400.0,
            estimated_notional_jpy=40_000.0,
        ),
        live_account_report=_account(
            available_funds=60_000.0,
            settled_cash_by_currency={"JPY": 41_000.0},
        ),
        live_fx_report=None,
    )

    assert result.ready is True
    assert result.endpoint_port == 4001
    assert result.settled_cash_currency == "JPY"
    assert result.required_settled_cash_amount == 41_000.0
    assert result.settled_cash_ready is True

    blocked = _evaluate(
        tmp_path,
        ticker="9432.T",
        readiness_report=_readiness(
            ticker="9432.T",
            quantity=100,
            limit_price=400.0,
            estimated_notional_jpy=40_000.0,
        ),
        live_account_report=_account(
            available_funds=60_000.0,
            settled_cash_by_currency={"JPY": 40_999.0},
        ),
        live_fx_report=None,
    )
    assert blocked.ready is False
    assert blocked.settled_cash_ready is False


def test_module_contains_no_broker_order_transport():
    source = Path(
        "src/ai_asset_platform/execution/live_pilot_same_run_preflight.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "reqOpenOrders(",
        "reqAllOpenOrders(",
        "reqExecutions(",
        "enable_live_trading = True",
        "whatIf=True",
    )
    for token in forbidden:
        assert token not in source
