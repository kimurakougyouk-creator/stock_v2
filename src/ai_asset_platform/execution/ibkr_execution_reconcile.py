"""Reconcile broker-confirmed IBKR Paper executions into durable local state.

Read-only with respect to IBKR. Broker execution ids are the cross-process
identity used to prevent one confirmed execution being counted twice under
both an application intent and a recovery intent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import order_manager
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence, IbkrPaperExecutionSnapshot,
    preview_ibkr_paper_execution_snapshot,
)
from ai_asset_platform.brokers.ibkr_fx_historical import preview_ibkr_paper_historical_fx_rate
from ai_asset_platform.core.settings import SETTINGS
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


def _ledger_identity(path: Path) -> tuple[set[str], set[str]]:
    intents: set[str] = set()
    exec_ids: set[str] = set()
    if not path.exists():
        return intents, exec_ids
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            intent = str(record.get("order_intent_id", "")).strip()
            if intent:
                intents.add(intent)
            for value in list(record.get("broker_exec_ids") or []):
                exec_id = str(value or "").strip()
                if exec_id:
                    exec_ids.add(exec_id)
    return intents, exec_ids


def _execution_reference_timestamp(raw: str) -> float | None:
    try:
        local_text, timezone_name = str(raw).strip().rsplit(" ", 1)
        local = datetime.strptime(local_text, "%Y%m%d %H:%M:%S")
        return local.replace(tzinfo=ZoneInfo(timezone_name)).timestamp()
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _execution_fx_to_account(execution: IbkrExecutionEvidence) -> float | None:
    source = str(execution.currency).strip().upper()
    target = str(SETTINGS.account_currency).strip().upper()
    if source == target:
        return 1.0
    reference_timestamp = _execution_reference_timestamp(execution.time)
    if len(source) != 3 or len(target) != 3 or reference_timestamp is None:
        return None
    try:
        evidence = preview_ibkr_paper_historical_fx_rate(
            base_currency=source, quote_currency=target,
            end_datetime=str(execution.time).strip(),
            reference_timestamp=reference_timestamp,
        )
    except Exception:
        return None
    return float(evidence.rate) if evidence.ready and evidence.rate and float(evidence.rate) > 0 else None


def _enrich_existing(path: Path, *, exec_id: str, intent: str, rate: float | None) -> bool:
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    changed = False
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            output.append(line)
            continue
        ids = [str(v or "").strip() for v in list(record.get("broker_exec_ids") or [])]
        record_intent = str(record.get("order_intent_id", "")).strip()
        if exec_id in ids or record_intent == intent:
            if exec_id not in ids:
                ids.append(exec_id)
                record["broker_exec_ids"] = ids
                changed = True
            if rate is not None and not record.get("fx_to_account_rate"):
                record["fx_to_account_rate"] = float(rate)
                changed = True
            if changed:
                output.append(json.dumps(record, ensure_ascii=False))
            else:
                output.append(line)
        else:
            output.append(line)
    if changed:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
        temporary.replace(path)
    return changed


def reconcile_execution_snapshot_to_ledger(
    snapshot: IbkrPaperExecutionSnapshot, *, order_log_path: Path,
) -> ReconciliationResult:
    if not snapshot.ready:
        return ReconciliationResult(0, 0, ("broker execution snapshot is not ready",))
    reconciled = 0
    skipped = 0
    errors: list[str] = []
    intents, known_exec_ids = _ledger_identity(order_log_path)
    for execution in snapshot.executions:
        try:
            exec_id = str(execution.exec_id).strip()
            if not exec_id:
                skipped += 1
                continue
            intent = _recovery_intent(execution)
            fx_rate = _execution_fx_to_account(execution)
            if exec_id in known_exec_ids or intent in intents:
                if _enrich_existing(order_log_path, exec_id=exec_id, intent=intent, rate=fx_rate):
                    reconciled += 1
                    known_exec_ids.add(exec_id)
                else:
                    skipped += 1
                continue
            raw_order_id = getattr(execution, "order_id", None)
            record_confirmed_fill(
                ticker=execution.symbol, side=execution.side,
                filled_quantity=execution.quantity, avg_fill_price=execution.price,
                currency=execution.currency, order_intent_id=intent,
                order_log_path=order_log_path, fx_to_account_rate=fx_rate,
                broker_exec_ids=[exec_id],
                broker_order_id=int(raw_order_id) if raw_order_id not in (None, 0, "") else None,
            )
            intents.add(intent)
            known_exec_ids.add(exec_id)
            reconciled += 1
        except Exception as exc:
            errors.append(f"{execution.exec_id or 'NO_EXEC_ID'}: {exc}")
    return ReconciliationResult(reconciled, skipped, tuple(errors))


def main() -> int:
    snapshot = preview_ibkr_paper_execution_snapshot()
    result = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=order_manager.ORDER_LOG_PATH)
    print("===== IBKR PAPER EXECUTION RECONCILIATION =====")
    print("SNAPSHOT READY   :", snapshot.ready)
    print("ENDPOINT PORT    :", snapshot.endpoint_port)
    print("EXECUTION COUNT  :", len(snapshot.executions))
    for index, item in enumerate(snapshot.executions, start=1):
        print(f"EXECUTION {index}: symbol={item.symbol} side={item.side} qty={item.quantity:g} price={item.price:g} currency={item.currency} exchange={item.exchange} order_id={item.order_id} perm_id={item.perm_id} exec_id={item.exec_id} time={item.time}")
    print("RECONCILED COUNT :", result.reconciled_count)
    print("SKIPPED COUNT    :", result.skipped_count)
    print("ERRORS           :", list(result.errors))
    print("REAL ORDER SENT  : False")
    return 0 if snapshot.ready and not result.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
