import json

import pytest

from ai_asset_platform.execution.ibkr_fill_reconcile import reconcile_confirmed_fill


def test_reconcile_confirmed_fill_from_execution_evidence(tmp_path):
    state = tmp_path / "fill.json"
    state.write_text(json.dumps({
        "execution_ledger": {"3": {"exec-1": [1.0, 765.45]}},
        "processed_filled": {"3": 1.0},
        "version": 1,
    }), encoding="utf-8")
    log = tmp_path / "paper_orders.jsonl"
    record = reconcile_confirmed_fill(
        fill_state_path=state, order_id=3, ticker="SPY", side="BUY",
        order_intent_id="spy-paper-e2e-20260822-001", order_log_path=log,
    )
    assert record["ticker"] == "SPY"
    assert record["side"] == "BUY"
    assert record["shares"] == 1
    assert record["reference_price"] == 765.45
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_reconcile_is_idempotent(tmp_path):
    state = tmp_path / "fill.json"
    state.write_text(json.dumps({
        "execution_ledger": {"3": {"exec-1": [1.0, 765.45]}},
        "processed_filled": {"3": 1.0},
    }), encoding="utf-8")
    log = tmp_path / "paper_orders.jsonl"
    kwargs = dict(fill_state_path=state, order_id=3, ticker="SPY", side="BUY",
                  order_intent_id="same", order_log_path=log)
    reconcile_confirmed_fill(**kwargs)
    reconcile_confirmed_fill(**kwargs)
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_reconcile_rejects_mismatched_evidence(tmp_path):
    state = tmp_path / "fill.json"
    state.write_text(json.dumps({
        "execution_ledger": {"3": {"exec-1": [1.0, 765.45]}},
        "processed_filled": {"3": 2.0},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="disagree"):
        reconcile_confirmed_fill(
            fill_state_path=state, order_id=3, ticker="SPY", side="BUY",
            order_intent_id="bad", order_log_path=tmp_path / "orders.jsonl",
        )
