import json
from pathlib import Path
from types import SimpleNamespace

import ai_asset_platform.execution.ibkr_execution_reconcile as reconcile_module
from ai_asset_platform.execution.ibkr_execution_reconcile import reconcile_execution_snapshot_to_ledger
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill


def test_confirmed_fill_persists_broker_execution_identity(tmp_path: Path):
    log = tmp_path / "paper_orders.jsonl"
    record = record_confirmed_fill(
        ticker="SPY", side="BUY", filled_quantity=1, avg_fill_price=765.45,
        currency="USD", order_intent_id="app-intent", order_log_path=log,
        broker_exec_ids=["E1", "E1", ""], broker_order_id=3,
    )
    assert record["broker_exec_ids"] == ["E1"]
    assert record["broker_order_id"] == 3


def test_reconciler_does_not_duplicate_application_fill_with_same_exec_id(tmp_path: Path, monkeypatch):
    log = tmp_path / "paper_orders.jsonl"
    record_confirmed_fill(
        ticker="SPY", side="BUY", filled_quantity=1, avg_fill_price=765.45,
        currency="USD", order_intent_id="overnight-paper-e2e:SPY:BUY:1:session",
        order_log_path=log, broker_exec_ids=["E1"], broker_order_id=3,
        fx_to_account_rate=147.0,
    )
    monkeypatch.setattr(reconcile_module, "_execution_fx_to_account", lambda execution: 147.0)
    execution = SimpleNamespace(
        exec_id="E1", order_id=3, symbol="SPY", side="BUY", quantity=1.0,
        price=765.45, currency="USD", time="20260821 16:33:06 US/Eastern",
    )
    snapshot = SimpleNamespace(ready=True, executions=(execution,))
    result = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=log)
    assert result.reconciled_count == 0
    assert result.skipped_count == 1
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["order_intent_id"].startswith("overnight-paper-e2e:")


def test_recovery_fill_itself_stores_exec_id(tmp_path: Path, monkeypatch):
    log = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(reconcile_module, "_execution_fx_to_account", lambda execution: 147.0)
    execution = SimpleNamespace(
        exec_id="E9", order_id=9, symbol="SPY", side="BUY", quantity=1.0,
        price=700.0, currency="USD", time="20260821 16:33:06 US/Eastern",
    )
    result = reconcile_execution_snapshot_to_ledger(
        SimpleNamespace(ready=True, executions=(execution,)), order_log_path=log
    )
    assert result.reconciled_count == 1
    row = json.loads(log.read_text(encoding="utf-8").strip())
    assert row["broker_exec_ids"] == ["E9"]
    assert row["broker_order_id"] == 9
