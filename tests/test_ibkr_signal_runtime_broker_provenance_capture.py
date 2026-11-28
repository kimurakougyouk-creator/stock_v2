from __future__ import annotations

import ai_asset_platform.execution.ibkr_signal_runtime as module


_FILL = {
    "order_intent_id": "signal-runner:paper-pilot:AAPL:BUY:1:2026-11-27",
    "broker_exec_fills": [{"exec_id": "0000e0d5.6b09300a.01.01", "shares": 1.0}],
}


def test_capture_helper_calls_capture_function_with_the_recorded_fill(monkeypatch):
    captured_args = {}

    def fake_capture(fill, *, local_commission_report):
        captured_args["fill"] = fill
        captured_args["local_commission_report"] = local_commission_report
        raise AssertionError("boom: simulated capture failure")

    monkeypatch.setattr(
        module, "capture_broker_provenance_evidence_for_fill", fake_capture
    )
    monkeypatch.setattr(module, "_load_json_object", lambda path: {"commissions": []})

    # Must never raise, even though the capture function itself raised.
    module._best_effort_capture_broker_provenance_evidence(_FILL)

    assert captured_args["fill"] is _FILL
    assert captured_args["local_commission_report"] == {"commissions": []}


def test_capture_helper_tolerates_unreadable_local_commission_report(monkeypatch):
    captured_args = {}

    def fake_capture(fill, *, local_commission_report):
        captured_args["local_commission_report"] = local_commission_report

    def fake_load_json_object(path):
        raise OSError("no such file")

    monkeypatch.setattr(
        module, "capture_broker_provenance_evidence_for_fill", fake_capture
    )
    monkeypatch.setattr(module, "_load_json_object", fake_load_json_object)

    module._best_effort_capture_broker_provenance_evidence(_FILL)

    assert captured_args["local_commission_report"] is None


def test_capture_helper_never_raises_when_capture_function_itself_is_broken(monkeypatch):
    def fake_capture(fill, *, local_commission_report):
        raise RuntimeError("no broker reachable in this test")

    monkeypatch.setattr(
        module, "capture_broker_provenance_evidence_for_fill", fake_capture
    )
    monkeypatch.setattr(module, "_load_json_object", lambda path: None)

    # The whole point of this helper: a capture failure must never propagate
    # and must never be mistaken for an order-confirmation failure.
    module._best_effort_capture_broker_provenance_evidence(_FILL)
