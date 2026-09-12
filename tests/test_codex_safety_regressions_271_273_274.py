from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from ai_asset_platform.brokers.ibkr_live_postfill_evidence import (
    IbkrLivePostFillSnapshot,
    LiveCommissionEvidence,
    LiveExecutionEvidence,
    match_live_postfill,
)
from ai_asset_platform.execution.live_pilot_completion import evaluate_live_pilot_completion
from ai_asset_platform.execution.live_pilot_send_journal import (
    create_consumed_authorization_journal,
    record_send_attempt,
)


NOW = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
FP = "a" * 64
INTENT = "live-pilot:9432:BUY:100:codex-regression"


def _marker(intent: str = INTENT):
    return {
        "state": "SEND_ATTEMPT_RECORDED",
        "intent_id": intent,
        "send_attempt_count": 1,
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
        "order_sent": False,
        "live_order_sent": False,
    }


def _journal():
    return {
        "state": "POSTFILL_PROVEN",
        "intent_id": INTENT,
        "send_attempt_count": 1,
        "order_id": 77,
        "perm_id": 88,
        "exec_id": "exec-1",
        "recovery_required": False,
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
    }


def _postfill(**overrides):
    data = {
        "schema_version": 2,
        "ready": True,
        "checked_at": NOW.isoformat(),
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FP,
        "executions": [{
            "exec_id": "exec-1", "order_id": 77, "perm_id": 88,
            "symbol": "9432", "sec_type": "STK", "currency": "JPY",
            "side": "BUY", "quantity": 100.0, "price": 400.0,
            "account_fingerprint": FP,
        }],
        "commissions": [{"exec_id": "exec-1", "commission": 10.0, "currency": "JPY"}],
        "order_sent": False,
        "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _account():
    return {
        "schema_version": 3, "ready": True, "checked_at": NOW.isoformat(),
        "connection_mode": "LIVE_READ_ONLY", "endpoint_port": 4001,
        "account_fingerprint": FP,
        "positions": [{"symbol": "9432", "sec_type": "STK", "currency": "JPY", "quantity": 100.0}],
        "order_sent": False, "live_order_sent": False,
    }


def _open_orders(**overrides):
    data = {
        "schema_version": 2, "ready": True, "checked_at": NOW.isoformat(),
        "connection_mode": "LIVE_READ_ONLY", "endpoint_port": 4001,
        "account_fingerprint": FP, "open_order_count": 0, "orders": [],
        "order_sent": False, "cancel_sent": False, "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _paper(**overrides):
    data = {
        "schema_version": 1, "status": "HEALTHY", "checked_at": NOW.isoformat(),
        "accounting_safe": True, "risk_safe": True,
        "monitor_order_sent": False, "live_order_sent": False,
        "broker": {
            "account_ready": True, "execution_snapshot_ready": True,
            "endpoint_port": 4002, "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
            "reconciliation_blocker_count": 0, "all_open_orders_ready": True,
            "open_order_count": 0, "open_orders": [],
        },
    }
    data.update(overrides)
    return data


def _completion(**overrides):
    params = dict(
        intent_id=INTENT, ticker="9432.T", side="BUY", quantity=100,
        expected_account_fingerprint=FP, send_journal=_journal(),
        attempt_marker=_marker(), postfill_report=_postfill(),
        final_account_report=_account(), final_open_orders_report=_open_orders(),
        paper_monitor_report=_paper(), now=NOW,
    )
    params.update(overrides)
    return evaluate_live_pilot_completion(**params)


def test_pilot_wide_attempt_marker_blocks_changed_intent(tmp_path: Path):
    consumed_a = {"status": "CONSUMED", "intent_id": "intent-a", "nonce": "nonce-a", "order_sent": False, "live_order_sent": False}
    create_consumed_authorization_journal(intent_id="intent-a", nonce="nonce-a", consumed_authorization=consumed_a, directory=tmp_path, now=NOW)
    record_send_attempt("intent-a", directory=tmp_path, now=NOW)
    consumed_b = {"status": "CONSUMED", "intent_id": "intent-b", "nonce": "nonce-b", "order_sent": False, "live_order_sent": False}
    with pytest.raises(PermissionError):
        create_consumed_authorization_journal(intent_id="intent-b", nonce="nonce-b", consumed_authorization=consumed_b, directory=tmp_path, now=NOW)


def test_completion_requires_authoritative_attempt_marker():
    assert _completion(attempt_marker=None).complete is False


def test_completion_rejects_wrong_or_missing_postfill_schema():
    assert _completion(postfill_report=_postfill(schema_version=1)).complete is False
    report = _postfill(); report.pop("schema_version")
    assert _completion(postfill_report=report).complete is False


def test_completion_rejects_warning_or_incomplete_paper_broker_state():
    assert _completion(paper_monitor_report=_paper(status="WARNING")).complete is False
    report = _paper(); report["broker"]["all_open_orders_ready"] = False
    assert _completion(paper_monitor_report=report).complete is False


def test_completion_rejects_open_order_account_substitution_and_malformed_count():
    assert _completion(final_open_orders_report=_open_orders(account_fingerprint="b" * 64)).complete is False
    assert _completion(final_open_orders_report=_open_orders(open_order_count=0.5)).complete is False
    assert _completion(final_open_orders_report=_open_orders(open_order_count=0, orders=[{"order_id": 1}])).complete is False


def test_completion_rejects_wrong_execution_currency():
    report = _postfill()
    report["executions"][0]["currency"] = "USD"
    report["commissions"][0]["currency"] = "USD"
    assert _completion(postfill_report=report).complete is False


def test_completion_rejects_exec_id_conflict_outside_target_set():
    report = _postfill()
    report["executions"].append({
        **report["executions"][0], "order_id": 999, "symbol": "OTHER"
    })
    assert _completion(postfill_report=report).complete is False


def test_completion_requires_exact_quantity_not_isclose():
    report = _postfill()
    report["executions"][0]["quantity"] = 100.0000000005
    assert _completion(postfill_report=report).complete is False


def test_direct_postfill_match_rejects_overflow_and_conflicting_exec_id():
    valid = LiveExecutionEvidence("exec-1", 77, 88, "9432", "STK", "JPY", "BUY", 100.0, 1e308, "", FP)
    conflict = replace(valid, order_id=999, symbol="OTHER")
    snap = IbkrLivePostFillSnapshot(
        attempted=True, connected=True, endpoint_port=4001, account_fingerprint=FP,
        executions=(valid, conflict),
        commissions=(LiveCommissionEvidence("exec-1", 1.0, "JPY", None),),
    )
    result = match_live_postfill(snap, expected_account_fingerprint=FP, ticker="9432.T", side="BUY", quantity=100, order_id=77, perm_id=88)
    assert result.ready is False
