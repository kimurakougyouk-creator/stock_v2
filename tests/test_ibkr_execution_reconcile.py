from pathlib import Path
from types import SimpleNamespace

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
    )


def test_reconcile_execution_snapshot_is_idempotent(tmp_path: Path):
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
    assert "broker-recovery:E1" in lines[0]


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
