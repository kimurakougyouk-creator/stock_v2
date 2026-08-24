"""Safely retire unrecoverable stale IBKR Paper fill rows from the active ledger.

This module never creates, changes, cancels, or transmits a broker order. It may
rewrite the local durable Paper ledger only when every targeted blocker is stale,
has no broker execution identity to recover from, and the current broker Paper
account proves the symbol is flat. Original rows are preserved verbatim in an
audit quarantine file and the complete pre-change ledger is backed up first.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.core.account_clock import account_now, account_today, account_zone
from ai_asset_platform.core.settings import SETTINGS, PlatformSettings


@dataclass(frozen=True)
class LegacyFillRetirementResult:
    changed: bool
    reason: str
    retired_count: int
    retired_intent_ids: tuple[str, ...]
    backup_path: Path | None
    quarantine_path: Path | None
    order_sent: bool = False


class LegacyFillRetirementError(ValueError):
    """Raised when a legacy blocker cannot be retired without guessing."""


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise LegacyFillRetirementError(
                    f"active ledger line {line_number} is invalid JSON"
                ) from exc
            if not isinstance(row, dict):
                raise LegacyFillRetirementError(
                    f"active ledger line {line_number} is not an object"
                )
            rows.append(row)
    return rows


def _missing_evidence_reason(record: dict, *, account_currency: str) -> str | None:
    if str(record.get("mode", "")).strip().upper() != "IBKR_PAPER":
        return None
    if str(record.get("status", "")).strip().upper() != "FILLED":
        return None

    currency = str(record.get("currency", "")).strip().upper()
    if not currency:
        return "missing-currency"
    if len(currency) != 3 or not currency.isalpha():
        return "invalid-currency"
    if currency == str(account_currency).strip().upper():
        return None
    try:
        fx = float(record.get("fx_to_account_rate"))
    except (TypeError, ValueError):
        fx = 0.0
    if fx <= 0:
        return "missing-historical-fx"
    return None


def _record_account_date(record: dict, *, settings: PlatformSettings):
    raw = record.get("created_at")
    if not raw:
        return None
    try:
        created = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    zone = account_zone(settings)
    if created.tzinfo is None:
        created = created.replace(tzinfo=zone)
    else:
        created = created.astimezone(zone)
    return created.date()


def _broker_symbol_quantity(account: IbkrPaperAccountSnapshot, symbol: str) -> float:
    target = str(symbol).strip().upper()
    return sum(
        float(position.quantity)
        for position in account.positions
        if str(position.symbol).strip().upper() == target
    )


def _broker_snapshot_safe(account: IbkrPaperAccountSnapshot, *, account_currency: str) -> bool:
    return (
        account.ready
        and str(account.base_currency).strip().upper() == str(account_currency).strip().upper()
        and account.available_funds is not None
        and account.available_funds >= 0
        and account.gross_position_value is not None
        and account.gross_position_value >= 0
        and not account.order_sent
    )


def _retirement_candidates(
    records: Iterable[dict],
    *,
    account: IbkrPaperAccountSnapshot,
    settings: PlatformSettings,
) -> tuple[list[dict], tuple[str, ...]]:
    account_currency = str(settings.account_currency).strip().upper()
    today = account_today(settings)
    candidates: list[dict] = []
    blockers: list[str] = []

    for index, record in enumerate(records, start=1):
        reason = _missing_evidence_reason(record, account_currency=account_currency)
        if reason is None:
            continue

        ticker = str(record.get("ticker", "")).strip().upper()
        intent = str(record.get("order_intent_id", "")).strip()
        key = f"{ticker or 'UNKNOWN'}:{intent or f'row-{index}'}:{reason}"

        if not ticker or not intent:
            blockers.append(f"{key}:missing-identity")
            continue
        if record.get("broker_order_id") not in (None, ""):
            blockers.append(f"{key}:broker-order-id-present")
            continue
        exec_ids = record.get("broker_exec_ids")
        if exec_ids not in (None, "", [], ()):
            blockers.append(f"{key}:broker-exec-id-present")
            continue

        record_date = _record_account_date(record, settings=settings)
        if record_date is None:
            blockers.append(f"{key}:missing-or-invalid-created-at")
            continue
        if record_date >= today:
            blockers.append(f"{key}:not-stale")
            continue

        broker_quantity = _broker_symbol_quantity(account, ticker)
        if broker_quantity != 0:
            blockers.append(f"{key}:broker-holds-{broker_quantity:g}")
            continue

        candidates.append(record)

    return candidates, tuple(blockers)


def _quarantine_existing_intents(path: Path) -> set[str]:
    if not path.exists():
        return set()
    result: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            record = row.get("record")
            if isinstance(record, dict):
                intent = str(record.get("order_intent_id", "")).strip()
                if intent:
                    result.add(intent)
    return result


def retire_stale_legacy_ibkr_fills(
    *,
    order_log_path: Path = Path("results/paper_orders.jsonl"),
    quarantine_path: Path = Path("results/quarantined_legacy_ibkr_fills.jsonl"),
    backup_dir: Path = Path("results/legacy_fill_backups"),
    settings: PlatformSettings = SETTINGS,
    account: IbkrPaperAccountSnapshot | None = None,
) -> LegacyFillRetirementResult:
    """Retire only stale, broker-flat, identity-less incomplete IBKR Paper fills."""
    records = _load_jsonl(order_log_path)
    if not records:
        return LegacyFillRetirementResult(
            False, "active ledger is empty; nothing to retire", 0, (), None, None
        )

    broker_account = account or preview_ibkr_paper_account_snapshot()
    account_currency = str(settings.account_currency).strip().upper()
    if not _broker_snapshot_safe(broker_account, account_currency=account_currency):
        raise LegacyFillRetirementError(
            "broker Paper account snapshot is not safe enough for legacy retirement"
        )

    candidates, blockers = _retirement_candidates(
        records, account=broker_account, settings=settings
    )
    if blockers:
        raise LegacyFillRetirementError(
            "legacy retirement remains blocked: " + "; ".join(blockers)
        )
    if not candidates:
        return LegacyFillRetirementResult(
            False, "no stale legacy evidence blocker requires retirement", 0, (), None, None
        )

    candidate_intents = {
        str(record.get("order_intent_id", "")).strip() for record in candidates
    }
    if "" in candidate_intents:
        raise LegacyFillRetirementError("retirement candidate is missing order_intent_id")

    remaining = [
        record
        for record in records
        if str(record.get("order_intent_id", "")).strip() not in candidate_intents
    ]

    now = account_now(settings)
    stamp = now.strftime("%Y%m%dT%H%M%S%z")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"paper_orders.before_legacy_retirement.{stamp}.jsonl"
    if backup_path.exists():
        raise LegacyFillRetirementError("backup path already exists; refusing overwrite")

    original_text = order_log_path.read_text(encoding="utf-8")
    backup_path.write_text(original_text, encoding="utf-8")

    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    already_quarantined = _quarantine_existing_intents(quarantine_path)
    with quarantine_path.open("a", encoding="utf-8") as handle:
        for record in candidates:
            intent = str(record["order_intent_id"]).strip()
            if intent in already_quarantined:
                continue
            payload = {
                "quarantined_at": now.isoformat(timespec="seconds"),
                "reason": "stale incomplete IBKR_PAPER fill; broker currently flat; no recoverable broker identity",
                "source": str(order_log_path),
                "record": record,
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    temporary_path = order_log_path.with_suffix(order_log_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as handle:
        for record in remaining:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary_path.replace(order_log_path)

    return LegacyFillRetirementResult(
        True,
        "stale incomplete legacy fills were retired from the active ledger without guessing missing evidence",
        len(candidates),
        tuple(sorted(candidate_intents)),
        backup_path,
        quarantine_path,
    )
