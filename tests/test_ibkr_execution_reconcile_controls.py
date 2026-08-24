from pathlib import Path

from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
)
from ai_asset_platform.execution.ibkr_execution_reconcile import (
    reconcile_execution_snapshot_to_ledger,
)
from ai_asset_platform.execution.ibkr_reconciliation_control import (
    acquire_reconciliation_pause,
    record_reconciliation_exclusions,
    release_reconciliation_pause,
)


def _snapshot(exec_id: str = "reset-exec"):
    return IbkrPaperExecutionSnapshot(
        connected=True,
        endpoint_port=4002,
        executions=(
            IbkrExecutionEvidence(
                exec_id=exec_id,
                order_id=99,
                perm_id=100,
                symbol="AAPL",
                sec_type="STK",
                currency="USD",
                exchange="OVERNIGHT",
                side="SELL",
                quantity=3.0,
                price=300.0,
                time="20260824 00:30:00 US/Eastern",
                account="DU_TEST",
            ),
        ),
        order_sent=False,
        errors=(),
    )


def test_reconciliation_skips_explicit_reset_execution(tmp_path: Path):
    ledger = tmp_path / "paper_orders.jsonl"
    exclusion = tmp_path / "excluded.jsonl"
    pause = tmp_path / "pause.lock"
    record_reconciliation_exclusions(
        ["reset-exec"],
        symbol="AAPL",
        reason="flat reset",
        order_intent_id="reset-intent",
        path=exclusion,
    )
    result = reconcile_execution_snapshot_to_ledger(
        _snapshot(),
        order_log_path=ledger,
        exclusion_path=exclusion,
        pause_path=pause,
    )
    assert result.reconciled_count == 0
    assert result.skipped_count == 1
    assert result.errors == ()
    assert not ledger.exists()


def test_reconciliation_pause_blocks_all_ledger_mutation(tmp_path: Path):
    ledger = tmp_path / "paper_orders.jsonl"
    exclusion = tmp_path / "excluded.jsonl"
    pause_path = tmp_path / "pause.lock"
    pause = acquire_reconciliation_pause("reset-intent", path=pause_path)
    try:
        result = reconcile_execution_snapshot_to_ledger(
            _snapshot(),
            order_log_path=ledger,
            exclusion_path=exclusion,
            pause_path=pause_path,
        )
        assert result.reconciled_count == 0
        assert "paused by a safety lock" in result.errors[0]
        assert not ledger.exists()
    finally:
        release_reconciliation_pause(pause)
