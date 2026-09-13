from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

import ai_asset_platform.execution.live_pilot_completion as subject


NOW = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64
INTENT = "live-pilot:9432:BUY:100:test"
EXEC_ID = "0001.abc.01"


def _stamp(offset: int = 0) -> str:
    return (NOW + timedelta(seconds=offset)).isoformat(timespec="seconds")


def _journal(**overrides) -> dict:
    data = {
        "schema_version": 2,
        "intent_id": INTENT,
        "nonce": "nonce-test",
        "state": "POSTFILL_PROVEN",
        "send_attempt_count": 1,
        "order_id": 77,
        "perm_id": 880077,
        "exec_id": EXEC_ID,
        "recovery_required": False,
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
    }
    data.update(overrides)
    return data


def _marker(**overrides) -> dict:
    data = {
        "schema_version": 2,
        "intent_id": INTENT,
        "nonce": "nonce-test",
        "state": "SEND_ATTEMPT_RECORDED",
        "automatic_resend_allowed": False,
        "automatic_cancel_allowed": False,
        "automatic_modify_allowed": False,
        "automatic_flatten_allowed": False,
        "automatic_close_allowed": False,
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


def _open_orders(count: int = 0, **overrides) -> dict:
    data = {
        "ready": True,
        "checked_at": _stamp(),
        "connection_mode": "LIVE_READ_ONLY",
        "endpoint_port": 4001,
        "account_fingerprint": FINGERPRINT,
        "open_order_count": count,
        "orders": [],
        "order_sent": False,
        "cancel_sent": False,
        "live_order_sent": False,
    }
    data.update(overrides)
    return data


def _paper(*, broker: dict | None = None, **overrides) -> dict:
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
            "account_ready": True,
            "execution_snapshot_ready": True,
            "endpoint_port": 4002,
            "reconciliation_next_action": "RECONCILIATION_EVIDENCE_IS_CLEAN",
            "all_open_orders_ready": True,
        }
        if broker is None
        else broker,
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
        "send_attempt_marker": _marker(),
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


def test_warning_paper_monitor_with_incomplete_broker_snapshot_blocks():
    result = _evaluate(
        paper_monitor_report=_paper(
            status="WARNING",
            broker={"reconciliation_blocker_count": 0, "open_order_count": 0},
        )
    )
    assert result.complete is False
    assert result.paper_monitor_safe is False


def test_wrong_open_orders_fingerprint_blocks():
    result = _evaluate(final_open_orders_report=_open_orders(account_fingerprint="b" * 64))
    assert result.complete is False
    assert any("open-orders" in item and "fingerprint mismatch" in item for item in result.blockers)


def test_execution_currency_mismatched_with_instrument_ticker_blocks():
    result = _evaluate(
        postfill_report=_postfill(
            executions=[
                {
                    "exec_id": EXEC_ID,
                    "order_id": 77,
                    "perm_id": 880077,
                    "symbol": "9432",
                    "sec_type": "STK",
                    "currency": "USD",
                    "side": "BUY",
                    "quantity": 100.0,
                    "price": 402.0,
                    "account_fingerprint": FINGERPRINT,
                }
            ],
            commissions=[{"exec_id": EXEC_ID, "commission": 80.0, "currency": "USD"}],
        )
    )
    assert result.complete is False
    assert any("instrument currency" in item for item in result.blockers)


def test_non_integer_open_order_count_fails_closed():
    result = _evaluate(final_open_orders_report=_open_orders(open_order_count=0.5))
    assert result.complete is False
    assert any("open-order count" in item for item in result.blockers)


def test_zero_open_order_count_with_nonempty_orders_list_fails_closed():
    result = _evaluate(
        final_open_orders_report=_open_orders(open_order_count=0, orders=[{"order_id": 1}])
    )
    assert result.complete is False
    assert any("orders list is not empty" in item for item in result.blockers)


def test_postfill_report_missing_order_sent_key_blocks():
    postfill = _postfill()
    del postfill["order_sent"]
    result = _evaluate(postfill_report=postfill)
    assert result.complete is False
    assert any("not clean read-only evidence" in item for item in result.blockers)


def test_open_orders_report_missing_cancel_sent_key_blocks():
    orders = _open_orders()
    del orders["cancel_sent"]
    result = _evaluate(final_open_orders_report=orders)
    assert result.complete is False
    assert any("not clean read-only evidence" in item for item in result.blockers)


def test_postfill_report_does_not_require_cancel_sent_key():
    postfill = _postfill()
    assert "cancel_sent" not in postfill
    result = _evaluate(postfill_report=postfill)
    assert result.complete is True


def test_partial_persist_failure_cannot_leave_stale_success_alert_paired_with_new_blocked_report(
    tmp_path: Path, monkeypatch
):
    report_path = tmp_path / "completion.json"
    alert_path = tmp_path / "alert.json"

    success = _evaluate()
    subject.persist_live_pilot_completion(success, report_path=report_path, alert_path=alert_path)

    blocked = _evaluate(final_open_orders_report=_open_orders(1))

    real_replace = Path.replace
    report_tmp = report_path.with_suffix(report_path.suffix + ".tmp")

    def failing_replace(self, target):
        if self == report_tmp:
            raise OSError("simulated crash before report replace")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)
    with pytest.raises(OSError, match="simulated crash"):
        subject.persist_live_pilot_completion(blocked, report_path=report_path, alert_path=alert_path)

    alert_payload = json.loads(alert_path.read_text(encoding="utf-8"))
    assert alert_payload["severity"] == "CRITICAL"


def test_missing_send_attempt_marker_blocks_even_with_postfill_proven_journal():
    result = _evaluate(send_attempt_marker=None)
    assert result.complete is False
    assert any("send-attempt marker" in item for item in result.blockers)


def test_send_attempt_marker_nonce_mismatch_blocks():
    result = _evaluate(send_attempt_marker=_marker(nonce="different-nonce"))
    assert result.complete is False
    assert any("send-attempt marker" in item for item in result.blockers)


def test_send_attempt_marker_with_automatic_resend_allowed_true_blocks():
    result = _evaluate(send_attempt_marker=_marker(automatic_resend_allowed=True))
    assert result.complete is False
    assert any("send-attempt marker" in item for item in result.blockers)


def test_stale_or_missing_postfill_schema_version_blocks():
    result = _evaluate(postfill_report=_postfill(schema_version=1))
    assert result.complete is False
    assert any("schema_version" in item for item in result.blockers)

    postfill = _postfill()
    del postfill["schema_version"]
    result = _evaluate(postfill_report=postfill)
    assert result.complete is False
    assert any("schema_version" in item for item in result.blockers)


def test_conflicting_exec_id_outside_matched_order_blocks():
    postfill = _postfill()
    conflicting_row = dict(postfill["executions"][0])
    conflicting_row["order_id"] = 999
    postfill["executions"].append(conflicting_row)
    result = _evaluate(postfill_report=postfill)
    assert result.complete is False
    assert any("conflicts with execution evidence" in item for item in result.blockers)


def test_extreme_price_overflow_in_gross_computation_fails_closed():
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
                    "quantity": 100.0,
                    "price": 1e308,
                    "account_fingerprint": FINGERPRINT,
                }
            ]
        )
    )
    assert result.complete is False
    assert any("overflowed" in item for item in result.blockers)


def test_near_exact_but_not_exact_quantity_now_fails_closed():
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
                    "quantity": 100.0000000005,
                    "price": 402.0,
                    "account_fingerprint": FINGERPRINT,
                }
            ]
        )
    )
    assert result.complete is False
    assert any("total quantity" in item for item in result.blockers)


def test_audit_live_pilot_completion_loads_and_requires_attempt_marker(tmp_path: Path):
    from ai_asset_platform.execution.live_pilot_send_journal import (
        create_consumed_authorization_journal,
        mark_order_acknowledged,
        mark_postfill_proven,
        record_send_attempt,
    )

    journal_dir = tmp_path / "journal"
    postfill_path = tmp_path / "postfill.json"
    account_path = tmp_path / "account.json"
    open_orders_path = tmp_path / "open_orders.json"
    paper_path = tmp_path / "paper.json"

    create_consumed_authorization_journal(
        intent_id=INTENT,
        nonce="nonce-test",
        consumed_authorization={
            "status": "CONSUMED",
            "intent_id": INTENT,
            "nonce": "nonce-test",
            "order_sent": False,
            "live_order_sent": False,
        },
        directory=journal_dir,
        now=NOW,
    )
    record_send_attempt(INTENT, directory=journal_dir, now=NOW)
    mark_order_acknowledged(INTENT, order_id=77, perm_id=880077, directory=journal_dir, now=NOW)
    mark_postfill_proven(
        INTENT, exec_id=EXEC_ID, order_id=77, perm_id=880077, directory=journal_dir, now=NOW
    )

    postfill_path.write_text(json.dumps(_postfill()), encoding="utf-8")
    account_path.write_text(json.dumps(_account()), encoding="utf-8")
    open_orders_path.write_text(json.dumps(_open_orders()), encoding="utf-8")
    paper_path.write_text(json.dumps(_paper()), encoding="utf-8")

    result = subject.audit_live_pilot_completion(
        intent_id=INTENT,
        ticker="9432.T",
        side="BUY",
        quantity=100,
        expected_account_fingerprint=FINGERPRINT,
        journal_dir=journal_dir,
        postfill_report_path=postfill_path,
        live_account_report_path=account_path,
        live_open_orders_report_path=open_orders_path,
        paper_monitor_report_path=paper_path,
        now=NOW,
    )
    assert result.complete is True

    marker_path = journal_dir / f"{INTENT.replace(':', '_')}.attempted.json"
    marker_path.unlink()

    result_after_marker_removed = subject.audit_live_pilot_completion(
        intent_id=INTENT,
        ticker="9432.T",
        side="BUY",
        quantity=100,
        expected_account_fingerprint=FINGERPRINT,
        journal_dir=journal_dir,
        postfill_report_path=postfill_path,
        live_account_report_path=account_path,
        live_open_orders_report_path=open_orders_path,
        paper_monitor_report_path=paper_path,
        now=NOW,
    )
    assert result_after_marker_removed.complete is False
    assert any("send-attempt marker" in item for item in result_after_marker_removed.blockers)


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
