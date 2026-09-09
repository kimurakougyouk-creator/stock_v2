from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

import ai_asset_platform.execution.live_pilot_completion as subject


NOW = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64
INTENT = "live-pilot:9432:BUY:100:test"
EXEC_ID = "0001.abc.01"


def _stamp(offset: int = 0) -> str:
    return (NOW + timedelta(seconds=offset)).isoformat(timespec="seconds")


NONCE = "nonce_ABC-123"


def _journal(**overrides) -> dict:
    data = {
        "schema_version": 2,
        "intent_id": INTENT,
        "nonce": NONCE,
        "state": "POSTFILL_PROVEN",
        "send_attempt_count": 1,
        "order_id": 77,
        "perm_id": 880077,
        "exec_id": EXEC_ID,
        "recovery_required": False,
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
    }
    data.update(overrides)
    return data


def _attempt_marker(**overrides) -> dict:
    data = {
        "schema_version": 2,
        "intent_id": INTENT,
        "nonce": NONCE,
        "state": "SEND_ATTEMPT_RECORDED",
        "recorded_at": _stamp(),
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
    }
    data.update(overrides)
    return data


def _global_attempt_marker(**overrides) -> dict:
    data = {
        "schema_version": 2,
        "intent_id": INTENT,
        "recorded_at": _stamp(),
        "automatic_resend_allowed": False,
    }
    data.update(overrides)
    return data


def _postfill(**overrides) -> dict:
    data = {
        "schema_version": 2,
        "ready": True,
        "checked_at": _stamp(),
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "executions": [
            {
                "exec_id": EXEC_ID,
                "order_id": 77,
                "perm_id": 880077,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "side": "BUY",
                "quantity": 100.0,
                "price": 402.0,
                "account_fingerprint": FINGERPRINT,
            }
        ],
        "commissions": [
            {"exec_id": EXEC_ID, "commission": 80.0, "currency": "JPY"}
        ],
        "order_sent": False,
        "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _account(*, position: float = 100.0, **overrides) -> dict:
    positions = []
    if position != 0:
        positions.append(
            {
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "quantity": position,
            }
        )
    data = {
        "schema_version": 3,
        "ready": True,
        "checked_at": _stamp(),
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "positions": positions,
        "order_sent": False,
        "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _open_orders(count: int = 0, *, orders: list | None = None, **overrides) -> dict:
    data = {
        "schema_version": 2,
        "ready": True,
        "checked_at": _stamp(),
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "open_order_count": count,
        "orders": orders if orders is not None else [],
        "order_sent": False,
        "cancel_sent": False,
        "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _paper(**overrides) -> dict:
    data = {
        "schema_version": 1,
        "status": "HEALTHY",
        "checked_at": _stamp(),
        "accounting_safe": True,
        "risk_safe": True,
        "monitor_order_sent": False,
        "live_order_sent": False,
        "broker": {
            "account_ready": True,
            "execution_snapshot_ready": True,
            "endpoint_port": 4002,
            "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
            "reconciliation_blocker_count": 0,
            "all_open_orders_ready": True,
            "open_order_count": 0,
        },
    }
    data.update(overrides)
    return data


def _evaluate(**overrides):
    params = {
        "intent_id": INTENT,
        "ticker": "9432.T",
        "side": "BUY",
        "quantity": 100,
        "expected_account_fingerprint": FINGERPRINT,
        "send_journal": _journal(),
        "send_attempt_marker": _attempt_marker(),
        "global_send_attempt_marker": _global_attempt_marker(),
        "postfill_report": _postfill(),
        "final_account_report": _account(),
        "final_open_orders_report": _open_orders(),
        "paper_monitor_report": _paper(),
        "now": NOW,
    }
    params.update(overrides)
    return subject.evaluate_live_pilot_completion(**params)


def test_exact_complete_buy_evidence_is_complete():
    result = _evaluate()
    assert result.complete is True
    assert result.status == "COMPLETE"
    assert result.exec_id == EXEC_ID
    assert result.exec_ids == (EXEC_ID,)
    assert result.execution_count == 1
    assert result.filled_quantity == 100.0
    assert result.execution_price == 402.0
    assert result.commission == 80.0
    assert result.commission_count == 1
    assert result.commission_currency == "JPY"
    assert result.final_position_quantity == 100.0
    assert result.final_open_order_count == 0
    assert result.endpoint_port == 4001


def test_split_fill_completion_aggregates_exec_ids_vwap_and_commissions():
    second = "0001.abc.02"
    result = _evaluate(
        postfill_report=_postfill(
            executions=[
                {
                    "exec_id": EXEC_ID,
                    "order_id": 77,
                    "perm_id": 880077,
                    "symbol": "9432",
                    "sec_type": "STK",
                    "currency": "JPY",
                    "side": "BUY",
                    "quantity": 40.0,
                    "price": 400.0,
                    "account_fingerprint": FINGERPRINT,
                },
                {
                    "exec_id": second,
                    "order_id": 77,
                    "perm_id": 880077,
                    "symbol": "9432",
                    "sec_type": "STK",
                    "currency": "JPY",
                    "side": "BUY",
                    "quantity": 60.0,
                    "price": 402.0,
                    "account_fingerprint": FINGERPRINT,
                },
            ],
            commissions=[
                {"exec_id": EXEC_ID, "commission": 30.0, "currency": "JPY"},
                {"exec_id": second, "commission": 50.0, "currency": "JPY"},
            ],
        )
    )
    assert result.complete is True
    assert result.exec_ids == (EXEC_ID, second)
    assert result.execution_count == 2
    assert result.filled_quantity == 100.0
    assert result.execution_price == 401.2
    assert result.commission == 80.0
    assert result.commission_count == 2
    assert result.commission_currency == "JPY"


def test_split_fill_underfilled_or_overfilled_never_completes():
    second = "0001.abc.02"
    base_commissions = [
        {"exec_id": EXEC_ID, "commission": 30.0, "currency": "JPY"},
        {"exec_id": second, "commission": 50.0, "currency": "JPY"},
    ]
    under = _postfill(
        executions=[
            {
                "exec_id": EXEC_ID,
                "order_id": 77,
                "perm_id": 880077,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "side": "BUY",
                "quantity": 40.0,
                "price": 400.0,
                "account_fingerprint": FINGERPRINT,
            },
            {
                "exec_id": second,
                "order_id": 77,
                "perm_id": 880077,
                "symbol": "9432",
                "sec_type": "STK",
                "currency": "JPY",
                "side": "BUY",
                "quantity": 50.0,
                "price": 402.0,
                "account_fingerprint": FINGERPRINT,
            },
        ],
        commissions=base_commissions,
    )
    result = _evaluate(postfill_report=under)
    assert result.complete is False
    assert any("total quantity" in item for item in result.blockers)

    over = _postfill(
        executions=[
            dict(under["executions"][0]),
            {**under["executions"][1], "quantity": 70.0},
        ],
        commissions=base_commissions,
    )
    result = _evaluate(postfill_report=over)
    assert result.complete is False
    assert any("total quantity" in item for item in result.blockers)


def test_duplicate_exec_id_or_missing_per_exec_commission_blocks():
    duplicate = _postfill(
        executions=[
            {**_postfill()["executions"][0], "quantity": 50.0},
            {**_postfill()["executions"][0], "quantity": 50.0},
        ]
    )
    result = _evaluate(postfill_report=duplicate)
    assert result.complete is False
    assert any("duplicate exec_id" in item for item in result.blockers)

    second = "0001.abc.02"
    missing_commission = _postfill(
        executions=[
            {**_postfill()["executions"][0], "quantity": 40.0},
            {
                **_postfill()["executions"][0],
                "exec_id": second,
                "quantity": 60.0,
            },
        ],
        commissions=[{"exec_id": EXEC_ID, "commission": 30.0, "currency": "JPY"}],
    )
    result = _evaluate(postfill_report=missing_commission)
    assert result.complete is False
    assert any(second in item for item in result.blockers)


def test_journal_anchor_exec_id_must_exist_in_final_execution_set():
    result = _evaluate(send_journal=_journal(exec_id="not-in-final-evidence"))
    assert result.complete is False
    assert any("journal exec_id" in item for item in result.blockers)


def test_sell_completion_requires_final_flat_position():
    result = _evaluate(
        side="SELL",
        send_journal=_journal(),
        postfill_report=_postfill(
            executions=[
                {
                    "exec_id": EXEC_ID,
                    "order_id": 77,
                    "perm_id": 880077,
                    "symbol": "9432",
                    "sec_type": "STK",
                    "currency": "JPY",
                    "side": "SELL",
                    "quantity": 100.0,
                    "price": 402.0,
                    "account_fingerprint": FINGERPRINT,
                }
            ]
        ),
        final_account_report=_account(position=0),
    )
    assert result.complete is True
    assert result.final_position_quantity == 0.0


def test_unknown_or_acknowledged_only_journal_never_completes():
    unknown = _evaluate(send_journal=_journal(state="UNKNOWN", recovery_required=True))
    assert unknown.complete is False
    assert any("POSTFILL_PROVEN" in item for item in unknown.blockers)

    acknowledged = _evaluate(send_journal=_journal(state="ORDER_ACKNOWLEDGED"))
    assert acknowledged.complete is False


def test_execution_identity_mismatch_blocks():
    postfill = _postfill()
    postfill["executions"][0]["perm_id"] = 999
    result = _evaluate(postfill_report=postfill)
    assert result.complete is False
    assert any("no matching final Live execution" in item for item in result.blockers)


def test_missing_or_duplicate_commission_blocks():
    missing = _postfill(commissions=[])
    assert _evaluate(postfill_report=missing).complete is False

    duplicate = _postfill()
    duplicate["commissions"].append(dict(duplicate["commissions"][0]))
    result = _evaluate(postfill_report=duplicate)
    assert result.complete is False
    assert any("found 2" in item for item in result.blockers)


def test_commission_currency_mismatch_blocks():
    result = _evaluate(
        postfill_report=_postfill(
            commissions=[{"exec_id": EXEC_ID, "commission": 1.0, "currency": "USD"}]
        )
    )
    assert result.complete is False
    assert any("commission currency" in item for item in result.blockers)


def test_wrong_final_position_blocks():
    result = _evaluate(final_account_report=_account(position=99))
    assert result.complete is False
    assert any("final Live position" in item for item in result.blockers)


def test_any_final_open_order_blocks():
    result = _evaluate(final_open_orders_report=_open_orders(1))
    assert result.complete is False
    assert "final Live open-order count is not zero" in result.blockers


def test_mixed_final_live_endpoints_block():
    result = _evaluate(final_open_orders_report=_open_orders(endpoint_port=7496))
    assert result.complete is False
    assert result.endpoint_port is None
    assert any("one Live endpoint" in item for item in result.blockers)


def test_wrong_account_fingerprint_blocks():
    result = _evaluate(final_account_report=_account(account_fingerprint="b" * 64))
    assert result.complete is False
    assert any("fingerprint mismatch" in item for item in result.blockers)


def test_stale_evidence_blocks():
    result = _evaluate(
        postfill_report=_postfill(checked_at=_stamp(-121)),
    )
    assert result.complete is False
    assert result.evidence_fresh is False
    assert "Live post-fill evidence is missing or stale" in result.blockers


def test_unsafe_paper_monitor_blocks():
    result = _evaluate(paper_monitor_report=_paper(risk_safe=False))
    assert result.complete is False
    assert result.paper_monitor_safe is False


def test_persist_writes_durable_success_alert(tmp_path: Path):
    result = _evaluate()
    report = tmp_path / "completion.json"
    alert = tmp_path / "alert.json"
    subject.persist_live_pilot_completion(result, report_path=report, alert_path=alert)

    report_payload = json.loads(report.read_text(encoding="utf-8"))
    alert_payload = json.loads(alert.read_text(encoding="utf-8"))
    assert report_payload["complete"] is True
    assert report_payload["execution_count"] == 1
    assert alert_payload["severity"] == "SUCCESS"
    assert alert_payload["delivery"] == "LOCAL_DURABLE_OPERATOR_ALERT"
    assert alert_payload["external_notification_claimed"] is False


def test_persist_blocked_alert_explicitly_forbids_retry(tmp_path: Path):
    result = _evaluate(final_open_orders_report=_open_orders(1))
    report = tmp_path / "completion.json"
    alert = tmp_path / "alert.json"
    subject.persist_live_pilot_completion(result, report_path=report, alert_path=alert)
    alert_payload = json.loads(alert.read_text(encoding="utf-8"))
    assert alert_payload["severity"] == "CRITICAL"
    assert "DO NOT RETRY AUTOMATICALLY" in alert_payload["message"]


def test_open_orders_account_fingerprint_mismatch_blocks():
    """Codex P1: a zero-order snapshot from a different Live account on the

    same port must not be accepted merely because the endpoint matches.
    """
    result = _evaluate(
        final_open_orders_report=_open_orders(account_fingerprint="b" * 64)
    )
    assert result.complete is False
    assert any("open-orders" in item and "fingerprint mismatch" in item for item in result.blockers)


def test_paper_monitor_missing_broker_readiness_fields_blocks():
    """Codex P1: zero-defaulted broker counters must not pass; the broker

    readiness/clean-reconciliation/audited-endpoint fields are required
    explicitly.
    """
    missing_readiness = _evaluate(
        paper_monitor_report=_paper(
            broker={
                "account_ready": False,
                "execution_snapshot_ready": True,
                "endpoint_port": 4002,
                "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
                "reconciliation_blocker_count": 0,
                "all_open_orders_ready": True,
                "open_order_count": 0,
            }
        )
    )
    assert missing_readiness.complete is False
    assert missing_readiness.paper_monitor_safe is False

    not_clean_action = _evaluate(
        paper_monitor_report=_paper(
            broker={
                "account_ready": True,
                "execution_snapshot_ready": True,
                "endpoint_port": 4002,
                "reconciliation_next_action": "BLOCKED_BROKER_NOT_READY",
                "reconciliation_blocker_count": 0,
                "all_open_orders_ready": True,
                "open_order_count": 0,
            }
        )
    )
    assert not_clean_action.complete is False
    assert not_clean_action.paper_monitor_safe is False

    wrong_endpoint = _evaluate(
        paper_monitor_report=_paper(
            broker={
                "account_ready": True,
                "execution_snapshot_ready": True,
                "endpoint_port": 9999,
                "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
                "reconciliation_blocker_count": 0,
                "all_open_orders_ready": True,
                "open_order_count": 0,
            }
        )
    )
    assert wrong_endpoint.complete is False
    assert wrong_endpoint.paper_monitor_safe is False


def test_paper_monitor_requires_exact_healthy_status_and_schema_and_explicit_false_flags():
    """Codex P1 (round 2): even with every broker field clean, a non-HEALTHY

    status, wrong/missing schema_version, or a merely-falsy (not exact
    ``False``) transport flag must still fail closed -- these do not rely on
    the field checks above to be caught.
    """
    warning_status = _evaluate(paper_monitor_report=_paper(status="WARNING"))
    assert warning_status.complete is False
    assert warning_status.paper_monitor_safe is False

    wrong_schema = _evaluate(paper_monitor_report=_paper(schema_version=2))
    assert wrong_schema.complete is False
    assert wrong_schema.paper_monitor_safe is False

    missing_schema = _evaluate(paper_monitor_report=_paper(schema_version=None))
    assert missing_schema.complete is False
    assert missing_schema.paper_monitor_safe is False

    falsy_not_false_flag = _evaluate(
        paper_monitor_report=_paper(monitor_order_sent=None)
    )
    assert falsy_not_false_flag.complete is False
    assert falsy_not_false_flag.paper_monitor_safe is False

    falsy_zero_flag = _evaluate(paper_monitor_report=_paper(live_order_sent=0))
    assert falsy_zero_flag.complete is False
    assert falsy_zero_flag.paper_monitor_safe is False


def test_execution_currency_mismatch_with_instrument_blocks():
    """Codex P1: a USD-labeled execution for a JPY instrument (9432.T) must

    not complete even if it matches the commission currency.
    """
    postfill = _postfill()
    postfill["executions"][0]["currency"] = "USD"
    postfill["commissions"][0]["currency"] = "USD"
    result = _evaluate(postfill_report=postfill)
    assert result.complete is False
    assert any("expected instrument currency" in item for item in result.blockers)


def test_malformed_open_order_count_fails_closed():
    """Codex P1: a non-integral open_order_count (e.g. 0.5) must not silently

    truncate to zero, and non-empty/missing order rows must fail closed.
    """
    non_integral = _evaluate(
        final_open_orders_report=_open_orders(0.5)
    )
    assert non_integral.complete is False
    assert non_integral.final_open_order_count is None

    # Codex re-review: a float that happens to be integral (e.g. 0.0) must
    # also fail closed, since the evidence contract requires a genuine
    # non-boolean int, not merely a numerically-zero value of any type.
    integral_float = _evaluate(final_open_orders_report=_open_orders(0.0))
    assert integral_float.complete is False
    assert integral_float.final_open_order_count is None

    boolean_count = _evaluate(final_open_orders_report=_open_orders(False))
    assert boolean_count.complete is False
    assert boolean_count.final_open_order_count is None

    inconsistent_rows = _evaluate(
        final_open_orders_report=_open_orders(0, orders=[{"order_id": 1}])
    )
    assert inconsistent_rows.complete is False
    assert any("open-order rows" in item for item in inconsistent_rows.blockers)


def test_missing_or_mismatched_send_attempt_marker_blocks():
    """Codex P1: the mutable summary journal alone (state=POSTFILL_PROVEN) is

    not sufficient; the separate irreversible .attempted.json marker must
    also be present and consistent.
    """
    missing_marker = _evaluate(send_attempt_marker=None)
    assert missing_marker.complete is False
    assert any("send-attempt marker" in item for item in missing_marker.blockers)

    mismatched_nonce = _evaluate(send_attempt_marker=_attempt_marker(nonce="different"))
    assert mismatched_nonce.complete is False
    assert any("send-attempt marker" in item for item in mismatched_nonce.blockers)

    resend_allowed = _evaluate(
        send_attempt_marker=_attempt_marker(automatic_resend_allowed=True)
    )
    assert resend_allowed.complete is False
    assert any("send-attempt marker" in item for item in resend_allowed.blockers)

    # Codex re-review: an obsolete/unsupported marker schema must fail closed
    # even if every other field looks consistent.
    wrong_schema = _evaluate(send_attempt_marker=_attempt_marker(schema_version=1))
    assert wrong_schema.complete is False
    assert any("send-attempt marker" in item for item in wrong_schema.blockers)

    missing_schema = _evaluate(send_attempt_marker=_attempt_marker(schema_version=None))
    assert missing_schema.complete is False
    assert any("send-attempt marker" in item for item in missing_schema.blockers)

    # Codex re-review: an empty marker nonce must not pass merely because it
    # equals an equally-empty journal nonce; both being blank is itself a
    # missing-evidence condition, not a match.
    both_nonces_empty = _evaluate(
        send_journal=_journal(nonce=""),
        send_attempt_marker=_attempt_marker(nonce=""),
    )
    assert both_nonces_empty.complete is False
    assert any("send-attempt marker" in item for item in both_nonces_empty.blockers)


def test_missing_or_mismatched_global_send_attempt_marker_blocks():
    """Codex P1 (round 8): the per-intent .attempted.json marker alone is not

    sufficient. If GLOBAL_SEND_ATTEMPT.lock is missing or bound to a
    different intent -- which is exactly the condition that would let a
    second, otherwise-unblocked send attempt for another intent be created
    -- this intent must not be reported COMPLETE either, since the
    campaign-wide one-send guarantee is no longer provably intact.
    """
    missing_global_marker = _evaluate(global_send_attempt_marker=None)
    assert missing_global_marker.complete is False
    assert any("global send-attempt marker" in item for item in missing_global_marker.blockers)

    wrong_intent = _evaluate(
        global_send_attempt_marker=_global_attempt_marker(intent_id="a-different-intent")
    )
    assert wrong_intent.complete is False
    assert any("global send-attempt marker" in item for item in wrong_intent.blockers)

    wrong_schema = _evaluate(global_send_attempt_marker=_global_attempt_marker(schema_version=1))
    assert wrong_schema.complete is False
    assert any("global send-attempt marker" in item for item in wrong_schema.blockers)

    resend_allowed = _evaluate(
        global_send_attempt_marker=_global_attempt_marker(automatic_resend_allowed=True)
    )
    assert resend_allowed.complete is False
    assert any("global send-attempt marker" in item for item in resend_allowed.blockers)


def test_conflicting_exec_id_outside_matched_set_blocks():
    """Codex P1: a conflicting row sharing an exec_id with a matched execution

    but disagreeing on order/account/symbol identity must fail closed even
    though the order/perm/account/symbol/side filter alone would drop it.
    """
    postfill = _postfill()
    conflicting_row = dict(postfill["executions"][0])
    conflicting_row["order_id"] = 999
    conflicting_row["perm_id"] = 111111
    postfill["executions"].append(conflicting_row)
    result = _evaluate(postfill_report=postfill)
    assert result.complete is False
    assert any("conflicting execution identity" in item for item in result.blockers)


def test_postfill_wrong_schema_version_blocks():
    """Codex P1: a fresh v1, missing-version, or arbitrary-version post-fill

    report must not reconcile against the multi-execution evidence contract.
    """
    missing_version = _evaluate(postfill_report=_postfill(schema_version=None))
    assert missing_version.complete is False
    assert any("not clean read-only evidence" in item for item in missing_version.blockers)

    old_version = _evaluate(postfill_report=_postfill(schema_version=1))
    assert old_version.complete is False
    assert any("not clean read-only evidence" in item for item in old_version.blockers)


def test_final_account_and_open_orders_schema_version_are_also_validated():
    """Codex P1 (round 2): the schema guard must not cover only the post-fill

    report; the final account and open-order reports must be validated
    against their own producers' current schema too.
    """
    wrong_account_schema = _evaluate(final_account_report=_account(schema_version=999))
    assert wrong_account_schema.complete is False
    assert any(
        "account" in item and "not clean read-only evidence" in item
        for item in wrong_account_schema.blockers
    )

    wrong_open_orders_schema = _evaluate(
        final_open_orders_report=_open_orders(schema_version=999)
    )
    assert wrong_open_orders_schema.complete is False
    assert any(
        "open-order" in item and "not clean read-only evidence" in item
        for item in wrong_open_orders_schema.blockers
    )


def test_clean_live_report_requires_exact_false_transport_flags():
    """Codex P1 (round 2): a merely falsy transport flag (None, 0, missing)

    must not be mistaken for the exact ``False`` that proves no transport
    occurred.
    """
    falsy_order_sent = _evaluate(postfill_report=_postfill(order_sent=None))
    assert falsy_order_sent.complete is False

    falsy_cancel_sent = _evaluate(final_open_orders_report=_open_orders(cancel_sent=0))
    assert falsy_cancel_sent.complete is False

    missing_live_order_sent = _postfill()
    del missing_live_order_sent["live_order_sent"]
    result = _evaluate(postfill_report=missing_live_order_sent)
    assert result.complete is False


def test_persist_invalidates_stale_success_alert_before_writing_report(tmp_path: Path):
    """Codex P1: if report persistence fails, the alert must already reflect

    the new (non-SUCCESS) severity rather than leaving a stale SUCCESS alert
    from a prior run next to the failure.
    """
    report = tmp_path / "completion.json"
    alert = tmp_path / "alert.json"
    success = _evaluate()
    subject.persist_live_pilot_completion(success, report_path=report, alert_path=alert)
    assert json.loads(alert.read_text(encoding="utf-8"))["severity"] == "SUCCESS"

    blocked = _evaluate(final_open_orders_report=_open_orders(1))

    original_durable_write = subject._durable_write_json

    def failing_durable_write(path, payload):
        if path == report:
            raise OSError("simulated disk failure while writing report")
        return original_durable_write(path, payload)

    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(subject, "_durable_write_json", failing_durable_write)
        with pytest.raises(OSError, match="simulated disk failure"):
            subject.persist_live_pilot_completion(blocked, report_path=report, alert_path=alert)

    # The alert must already say CRITICAL even though the report write failed.
    assert json.loads(alert.read_text(encoding="utf-8"))["severity"] == "CRITICAL"


def test_persist_never_publishes_success_before_the_report_is_durable(tmp_path: Path):
    """Codex P1 (round 2): the mirror-image failure. If a COMPLETE result's

    own report write fails, the alert must never have been promoted to
    SUCCESS -- an operator or downstream consumer must not be able to see a
    durable SUCCESS alert with no (or a stale) completion report behind it.
    """
    report = tmp_path / "completion.json"
    alert = tmp_path / "alert.json"
    success = _evaluate()

    original_durable_write = subject._durable_write_json

    def failing_durable_write(path, payload):
        if path == report:
            raise OSError("simulated disk failure while writing report")
        return original_durable_write(path, payload)

    import pytest

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(subject, "_durable_write_json", failing_durable_write)
        with pytest.raises(OSError, match="simulated disk failure"):
            subject.persist_live_pilot_completion(success, report_path=report, alert_path=alert)

    assert not report.exists()
    assert json.loads(alert.read_text(encoding="utf-8"))["severity"] != "SUCCESS"

    # Once the failure is resolved, a clean retry still reaches SUCCESS with
    # a durable report backing it.
    subject.persist_live_pilot_completion(success, report_path=report, alert_path=alert)
    assert json.loads(alert.read_text(encoding="utf-8"))["severity"] == "SUCCESS"
    assert json.loads(report.read_text(encoding="utf-8"))["complete"] is True


def test_durable_write_json_fsyncs_file_and_directory(tmp_path: Path, monkeypatch):
    """Codex P1 (round 3): both the temp file and the containing directory

    must be fsynced, or a crash right after this call can lose the rename or
    reorder it relative to another durable write.
    """
    calls = []
    original_fsync = os.fsync

    def spy_fsync(fd):
        calls.append(fd)
        return original_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    target = tmp_path / "durable.json"
    subject._durable_write_json(target, {"a": 1})

    assert target.exists()
    assert len(calls) >= 2


def test_write_full_loops_over_short_writes_and_rejects_no_progress(tmp_path: Path, monkeypatch):
    """Codex P1 (round 4): a short ``os.write`` must not silently persist

    truncated JSON; the helper must loop until every byte is written and
    fail rather than fsync/rename on a write that made no progress.
    """
    import pytest

    data = b"x" * 100
    target = tmp_path / "short_write_target.bin"
    original_write = os.write

    counts = {"calls": 0}

    def short_write(fd, chunk):
        counts["calls"] += 1
        # Only ever accept at most 7 bytes per call, forcing many short writes.
        return original_write(fd, chunk[:7])

    monkeypatch.setattr(os, "write", short_write)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        subject._write_full(descriptor, data)
    finally:
        os.close(descriptor)

    assert target.read_bytes() == data
    assert counts["calls"] > 1

    zero_progress_target = tmp_path / "zero_progress.bin"
    monkeypatch.setattr(os, "write", lambda fd, chunk: 0)
    descriptor = os.open(zero_progress_target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with pytest.raises(OSError, match="no progress"):
            subject._write_full(descriptor, data)
    finally:
        os.close(descriptor)


def test_paper_safe_rejects_non_exact_int_counters():
    """Codex P1 (round 3): 0.0, "0", and False must not satisfy the

    reconciliation-blocker/open-order counters, matching the exact-int
    contract already required for the final Live open-order count.
    """
    float_blockers = _evaluate(
        paper_monitor_report=_paper(
            broker={
                "account_ready": True,
                "execution_snapshot_ready": True,
                "endpoint_port": 4002,
                "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
                "reconciliation_blocker_count": 0.0,
                "all_open_orders_ready": True,
                "open_order_count": 0,
            }
        )
    )
    assert float_blockers.complete is False
    assert float_blockers.paper_monitor_safe is False

    string_open_orders = _evaluate(
        paper_monitor_report=_paper(
            broker={
                "account_ready": True,
                "execution_snapshot_ready": True,
                "endpoint_port": 4002,
                "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
                "reconciliation_blocker_count": 0,
                "all_open_orders_ready": True,
                "open_order_count": "0",
            }
        )
    )
    assert string_open_orders.complete is False
    assert string_open_orders.paper_monitor_safe is False

    boolean_blockers = _evaluate(
        paper_monitor_report=_paper(
            broker={
                "account_ready": True,
                "execution_snapshot_ready": True,
                "endpoint_port": 4002,
                "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
                "reconciliation_blocker_count": False,
                "all_open_orders_ready": True,
                "open_order_count": 0,
            }
        )
    )
    assert boolean_blockers.complete is False
    assert boolean_blockers.paper_monitor_safe is False


def test_summary_journal_requires_current_schema_and_all_five_automatic_flags():
    """Codex P1 (round 3): the mutable summary journal itself must be checked

    against the current schema and all five no-automatic-action fields, not
    only the irreversible attempt marker.
    """
    wrong_schema = _evaluate(send_journal=_journal(schema_version=1))
    assert wrong_schema.complete is False
    assert any("POSTFILL_PROVEN" in item for item in wrong_schema.blockers)

    missing_schema = _evaluate(send_journal=_journal(schema_version=None))
    assert missing_schema.complete is False
    assert any("POSTFILL_PROVEN" in item for item in missing_schema.blockers)

    flatten_allowed = _evaluate(send_journal=_journal(automatic_flatten_allowed=True))
    assert flatten_allowed.complete is False
    assert any("POSTFILL_PROVEN" in item for item in flatten_allowed.blockers)

    close_allowed = _evaluate(send_journal=_journal(automatic_close_allowed=True))
    assert close_allowed.complete is False
    assert any("POSTFILL_PROVEN" in item for item in close_allowed.blockers)


def test_execution_quantity_requires_exact_decimal_equality_not_isclose():
    """Ported PR #280 finding: math.isclose(1.0000000005, 1.0) would accept a

    real underfill/overfill. Decimal equality must reject even a tiny
    discrepancy.
    """
    postfill = _postfill()
    postfill["executions"][0]["quantity"] = 100.0000000005
    result = _evaluate(postfill_report=postfill)
    assert result.complete is False
    assert any("total quantity" in item for item in result.blockers)


def test_non_finite_aggregate_from_extreme_values_fails_closed_not_crashes():
    """Ported PR #280 finding: an execution price with an extreme exponent

    can overflow during Decimal multiplication; this must produce a
    blocked result, not raise uncaught.
    """
    postfill = _postfill()
    postfill["executions"][0]["price"] = "1e9999"
    result = _evaluate(postfill_report=postfill)
    assert result.complete is False
    assert any("non-finite" in item for item in result.blockers)


def test_audit_live_pilot_completion_catches_decimal_exceptions_and_blocks(monkeypatch):
    """If evaluate_live_pilot_completion somehow still raises a

    DecimalException/ArithmeticError on malformed evidence, the wrapper must
    persist a BLOCKED result rather than let the audit abort uncaught.
    """
    from decimal import DivisionByZero

    def _raise(**kwargs):
        raise DivisionByZero("simulated overflow deep in aggregation")

    monkeypatch.setattr(subject, "evaluate_live_pilot_completion", _raise)
    result = subject.audit_live_pilot_completion(
        intent_id=INTENT,
        ticker="9432.T",
        side="BUY",
        quantity=100,
        expected_account_fingerprint=FINGERPRINT,
        journal_dir=Path("results/live_pilot_send_journal"),
        now=NOW,
    )
    assert result.complete is False
    assert result.status == "BLOCKED"
    assert any("malformed evidence" in item for item in result.blockers)


def test_send_attempt_count_requires_exact_non_boolean_int():
    """Ported PR #280 finding: a coerced send_attempt_count (float, string,

    or boolean) must not satisfy the exact-one requirement.
    """
    for bad_count in (1.0, "1", True):
        result = _evaluate(send_journal=_journal(send_attempt_count=bad_count))
        assert result.complete is False, bad_count
        assert any("POSTFILL_PROVEN" in item for item in result.blockers), bad_count


def test_cancel_sent_true_is_rejected_even_on_reports_that_do_not_require_it():
    """Ported PR #280 finding: postfill/account reports never define

    cancel_sent in their own schema, but an explicit cancel_sent: true must
    still be rejected rather than silently ignored.
    """
    postfill_with_cancel = _postfill(cancel_sent=True)
    result = _evaluate(postfill_report=postfill_with_cancel)
    assert result.complete is False
    assert any("post-fill" in item and "not clean" in item for item in result.blockers)

    account_with_cancel = _account(cancel_sent=True)
    result = _evaluate(final_account_report=account_with_cancel)
    assert result.complete is False
    assert any("account" in item and "not clean" in item for item in result.blockers)


def test_module_contains_no_broker_transport():
    source = Path(
        "src/ai_asset_platform/execution/live_pilot_completion.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "reqExecutions(",
        "reqAllOpenOrders(",
        "enable_live_trading = True",
    )
    for token in forbidden:
        assert token not in source
