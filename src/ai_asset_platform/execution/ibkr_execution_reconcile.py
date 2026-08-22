"""Reconcile broker-confirmed IBKR Paper executions into durable local state.

Read-only with respect to IBKR: this module consumes execution snapshots and
writes only the local durable order ledger. It never creates, changes, cancels,
or transmits broker orders. Existing local intent ids are preserved; broker
exec_id is used only to create a deterministic recovery intent when evidence is
missing locally.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
)
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill


@dataclass(frozen=True)
class ReconciliationResult:
    reconciled_count: int
    skipped_count: int
    errors: tuple[str, ...] = ()


def _recovery_intent(execution: IbkrExecutionEvidence) -> str:
    exec_id = str(execution.exec_id).strip()
    if not exec_id:
        raise ValueError("exec_id is required for deterministic reconciliation")
    return f"broker-recovery:{exec_id}"


def reconcile_execution_snapshot_to_ledger(
    snapshot: IbkrPaperExecutionSnapshot,
    *,
    order_log_path: Path,
) -> ReconciliationResult:
    """Persist missing broker execution evidence idempotently into local state."""
    if not snapshot.ready:
        return ReconciliationResult(0, 0, ("broker execution snapshot is not ready",))

    reconciled = 0
    skipped = 0
    errors: list[str] = []
    for execution in snapshot.executions:
        try:
            if not execution.exec_id:
                skipped += 1
                continue
            record_confirmed_fill(
                ticker=execution.symbol,
                side=execution.side,
                filled_quantity=execution.quantity,
                avg_fill_price=execution.price,
                currency=execution.currency,
                order_intent_id=_recovery_intent(execution),
                order_log_path=order_log_path,
            )
            reconciled += 1
        except Exception as exc:
            errors.append(f"{execution.exec_id or 'NO_EXEC_ID'}: {exc}")
    return ReconciliationResult(reconciled, skipped, tuple(errors))
