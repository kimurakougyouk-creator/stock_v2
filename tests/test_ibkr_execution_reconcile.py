import json
from pathlib import Path
from types import SimpleNamespace

import ai_asset_platform.execution.ibkr_execution_reconcile as module
from ai_asset_platform.execution.ibkr_execution_reconcile import (
    reconcile_execution_snapshot_to_ledger,
)


def _execution(exec_id: str = "E1"):
    return SimpleNamespace(
        exec_id=exec_id,
        symbol="SPY",
        side="BUY",
        quantity=1.0,
        price=765.45,
        currency="USD",
        time="20260821 16:33:06 US/Eastern",
    )


def _ready_fx(**kwargs):
    return SimpleNamespace(ready=True, rate=147.25)


def test_reconcile_execution_snapshot_is_idempotent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(module, "preview_ibkr_paper_historical_fx_rate", _ready_fx)
    log = tmp_path / "paper_orders.jsonl"
    snapshot = SimpleNamespace(ready=True, executions=(_execution(),))

    first = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=log)
    second = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=log)

    assert first.reconciled_count == 1
    assert first.skipped_count == 0
    assert second.reconciled_count == 0
    assert second.skipped_count == 1
    lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["order_intent_id"] == "broker-recovery:E1"
    assert record["currency"] == "USD"
    assert record["fx_to_account_rate"] == 147.25


def test_reconcile_enriches_existing_recovery_with_fx(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(module, "preview_ibkr_paper_historical_fx_rate", _ready_fx)
    log = tmp_path / "paper_orders.jsonl"
    log.write_text(
        json.dumps({
            "mode": "IBKR_PAPER",
            "ticker": "SPY",
            "side": "BUY",
            "shares": 1,
            "reference_price": 765.45,
            "currency": "USD",
            "status": "FILLED",
            "order_intent_id": "broker-recovery:E1",
        }) + "\n",
        encoding="utf-8",
    )
    snapshot = SimpleNamespace(ready=True, executions=(_execution(),))
    result = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=log)
    record = json.loads(log.read_text(encoding="utf-8").strip())
    assert result.reconciled_count == 1
    assert result.skipped_count == 0
    assert record["fx_to_account_rate"] == 147.25


def test_reconcile_execution_snapshot_skips_missing_exec_id(tmp_path: Path):
    snapshot = SimpleNamespace(ready=True, executions=(_execution(""),))
    result = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=tmp_path / "x.jsonl")
    assert result.reconciled_count == 0
    assert result.skipped_count == 1


def test_reconcile_execution_snapshot_fails_closed_when_not_ready(tmp_path: Path):
    snapshot = SimpleNamespace(ready=False, executions=())
    result = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=tmp_path / "x.jsonl")
    assert result.reconciled_count == 0
    assert result.errors
