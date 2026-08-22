"""Reconcile broker-confirmed IBKR Paper executions into durable local state.

Read-only with respect to IBKR: this module consumes execution snapshots and
writes only the local durable order ledger. It never creates, changes, cancels,
or transmits broker orders. Existing local intent ids are preserved; broker
exec_id is used only to create a deterministic recovery intent when evidence is
missing locally.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import order_manager
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
    preview_ibkr_paper_execution_snapshot,
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


def _existing_intents(path: Path) -> set[str]:
    intents: set[str] = set()
    if not path.exists():
        return intents
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            intent = str(record.get("order_intent_id", "")).strip()
            if intent:
                intents.add(intent)
    return intents


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
    existing = _existing_intents(order_log_path)
    for execution in snapshot.executions:
        try:
            if not execution.exec_id:
                skipped += 1
                continue
            intent = _recovery_intent(execution)
            if intent in existing:
                skipped += 1
                continue
            record_confirmed_fill(
                ticker=execution.symbol,
                side=execution.side,
                filled_quantity=execution.quantity,
                avg_fill_price=execution.price,
                currency=execution.currency,
                order_intent_id=intent,
                order_log_path=order_log_path,
            )
            existing.add(intent)
            reconciled += 1
        except Exception as exc:
            errors.append(f"{execution.exec_id or 'NO_EXEC_ID'}: {exc}")
    return ReconciliationResult(reconciled, skipped, tuple(errors))


def main() -> int:
    snapshot = preview_ibkr_paper_execution_snapshot()
    result = reconcile_execution_snapshot_to_ledger(
        snapshot,
        order_log_path=order_manager.ORDER_LOG_PATH,
    )
    print("===== IBKR PAPER EXECUTION RECONCILIATION =====")
    print("SNAPSHOT READY   :", snapshot.ready)
    print("ENDPOINT PORT    :", snapshot.endpoint_port)
    print("EXECUTION COUNT  :", len(snapshot.executions))
    for index, item in enumerate(snapshot.executions, start=1):
        print(
            f"EXECUTION {index}: symbol={item.symbol} side={item.side} qty={item.quantity:g} "
            f"price={item.price:g} currency={item.currency} exchange={item.exchange} "
            f"order_id={item.order_id} perm_id={item.perm_id} exec_id={item.exec_id} time={item.time}"
        )
    print("RECONCILED COUNT :", result.reconciled_count)
    print("SKIPPED COUNT    :", result.skipped_count)
    print("ERRORS           :", list(result.errors))
    print("REAL ORDER SENT  : False")
    return 0 if snapshot.ready and not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
