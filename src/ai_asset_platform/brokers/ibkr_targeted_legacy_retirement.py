from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_legacy_fill_retirement import (
    LegacyFillRetirementError,
    _broker_snapshot_safe,
    _broker_symbol_quantity,
    _load_jsonl,
    _missing_evidence_reason,
    _quarantine_existing_intents,
    _record_account_date,
)
from ai_asset_platform.core.account_clock import account_now, account_today
from ai_asset_platform.core.settings import SETTINGS, PlatformSettings


@dataclass(frozen=True)
class TargetedLegacyRetirementResult:
    changed: bool
    reason: str
    intent_id: str
    backup_path: Path | None
    quarantine_path: Path | None
    order_sent: bool = False


def retire_stale_legacy_ibkr_fill_by_intent(
    intent_id: str,
    *,
    order_log_path: Path = Path("results/paper_orders.jsonl"),
    quarantine_path: Path = Path("results/quarantined_legacy_ibkr_fills.jsonl"),
    backup_dir: Path = Path("results/legacy_fill_backups"),
    settings: PlatformSettings = SETTINGS,
    account: IbkrPaperAccountSnapshot | None = None,
) -> TargetedLegacyRetirementResult:
    target_intent = str(intent_id).strip()
    if not target_intent:
        raise ValueError("intent_id is required")

    records = _load_jsonl(order_log_path)
    matches = [
        row for row in records
        if str(row.get("order_intent_id", "")).strip() == target_intent
    ]
    if len(matches) != 1:
        raise LegacyFillRetirementError(
            f"targeted retirement requires exactly one active row; found {len(matches)}"
        )
    record = matches[0]
    account_currency = str(settings.account_currency).strip().upper()
    reason = _missing_evidence_reason(record, account_currency=account_currency)
    if reason is None:
        raise LegacyFillRetirementError(
            "targeted row is not an incomplete legacy evidence blocker"
        )
    ticker = str(record.get("ticker", "")).strip().upper()
    if not ticker:
        raise LegacyFillRetirementError("targeted row is missing ticker")
    if record.get("broker_order_id") not in (None, ""):
        raise LegacyFillRetirementError("targeted row has broker_order_id and remains recoverable")
    if record.get("broker_exec_ids") not in (None, "", [], ()):
        raise LegacyFillRetirementError("targeted row has broker_exec_ids and remains recoverable")
    record_date = _record_account_date(record, settings=settings)
    if record_date is None or record_date >= account_today(settings):
        raise LegacyFillRetirementError("targeted row is not safely stale")

    broker_account = account or preview_ibkr_paper_account_snapshot()
    if not _broker_snapshot_safe(broker_account, account_currency=account_currency):
        raise LegacyFillRetirementError(
            "broker Paper account snapshot is not safe enough for targeted retirement"
        )
    broker_quantity = _broker_symbol_quantity(broker_account, ticker)
    if broker_quantity != 0:
        raise LegacyFillRetirementError(
            f"targeted retirement requires broker-flat {ticker}; found {broker_quantity:g}"
        )

    now = account_now(settings)
    stamp = now.strftime("%Y%m%dT%H%M%S%z")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"paper_orders.before_targeted_retirement.{stamp}.jsonl"
    if backup_path.exists():
        raise LegacyFillRetirementError("backup path already exists; refusing overwrite")
    backup_path.write_text(order_log_path.read_text(encoding="utf-8"), encoding="utf-8")

    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    already = _quarantine_existing_intents(quarantine_path)
    if target_intent not in already:
        with quarantine_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "quarantined_at": now.isoformat(timespec="seconds"),
                        "reason": (
                            "targeted stale incomplete IBKR_PAPER fill retired only after "
                            "broker proved the symbol flat"
                        ),
                        "source": str(order_log_path),
                        "record": record,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    remaining = [
        row for row in records
        if str(row.get("order_intent_id", "")).strip() != target_intent
    ]
    temporary = order_log_path.with_suffix(order_log_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in remaining:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(order_log_path)

    return TargetedLegacyRetirementResult(
        changed=True,
        reason=(
            "targeted stale legacy row retired after broker-flat proof; unrelated blockers were untouched"
        ),
        intent_id=target_intent,
        backup_path=backup_path,
        quarantine_path=quarantine_path,
        order_sent=False,
    )
