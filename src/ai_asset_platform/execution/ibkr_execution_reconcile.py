"""Reconcile broker-confirmed IBKR Paper executions into durable local state.

Read-only with respect to IBKR: this module consumes execution snapshots and
writes only the local durable order ledger. It never creates, changes, cancels,
or transmits broker orders. Broker historical MIDPOINT data may be used to
attach account-currency FX evidence at the exact confirmed execution time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import order_manager
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
    preview_ibkr_paper_execution_snapshot,
)
from ai_asset_platform.brokers.ibkr_fx_historical import (
    preview_ibkr_paper_historical_fx_rate,
)
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


def _execution_reference_timestamp(raw: str) -> float | None:
    value = str(raw).strip()
    try:
        local_text, timezone_name = value.rsplit(" ", 1)
        local = datetime.strptime(local_text, "%Y%m%d %H:%M:%S")
        return local.replace(tzinfo=ZoneInfo(timezone_name)).timestamp()
    except Exception:
        return None


def _execution_fx_to_account(execution: IbkrExecutionEvidence) -> float | None:
    source = str(execution.currency).strip().upper()
    target = str(SETTINGS.account_currency).strip().upper()
    if source == target:
        return 1.0
    if len(source) != 3 or len(target) != 3:
        return None
    reference_timestamp = _execution_reference_timestamp(execution.time)
    if reference_timestamp is None:
        return None
    try:
        evidence = preview_ibkr_paper_historical_fx_rate(
            base_currency=source,
            quote_currency=target,
            end_datetime=str(execution.time).strip(),
            reference_timestamp=reference_timestamp,
        )
    except Exception:
        return None
    if not evidence.ready or evidence.rate is None:
        return None
    rate = float(evidence.rate)
    return rate if rate > 0 else None


def _enrich_existing_intent_fx(path: Path, *, intent: str, rate: float) -> bool:
    if not path.exists() or rate <= 0:
        return False
    original = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    changed = False
    for line in original:
        if not line.strip():
            output.append(line)
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            output.append(line)
            continue
        if (
            str(record.get("order_intent_id", "")).strip() == intent
            and not record.get("fx_to_account_rate")
        ):
            record["fx_to_account_rate"] = float(rate)
            output.append(json.dumps(record, ensure_ascii=False))
            changed = True
        else:
            output.append(line)
    if changed:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
        temporary.replace(path)
    return changed


def reconcile_execution_snapshot_to_ledger(
    snapshot: IbkrPaperExecutionSnapshot,
    *,
    order_log_path: Path,
) -> ReconciliationResult:
    """Persist broker execution evidence and fill-time FX idempotently."""
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
            fx_rate = _execution_fx_to_account(execution)
            if intent in existing:
                if fx_rate is not None and _enrich_existing_intent_fx(
                    order_log_path,
                    intent=intent,
                    rate=fx_rate,
                ):
                    reconciled += 1
                else:
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
                fx_to_account_rate=fx_rate,
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
