"""Safely quarantine verified derivative rows from the legacy whole-share Paper ledger.

Only rows whose broker execution identity exactly matches immutable, previously
captured IBKR Paper derivative evidence are eligible. Current broker Paper
positions for the matching derivative security type must be flat. The original
ledger is backed up and matching rows are preserved verbatim in quarantine.
No broker order is created, changed, cancelled, or transmitted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from ai_asset_platform.accounting.verified_derivative_broker_evidence import (
    VERIFIED_ESU6_EXECUTIONS,
    VERIFIED_SPY_OPTION_EXECUTIONS,
)
from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.core.account_clock import account_now
from ai_asset_platform.core.settings import SETTINGS, PlatformSettings


VERIFIED_DERIVATIVE_EXECUTIONS = (
    *VERIFIED_ESU6_EXECUTIONS,
    *VERIFIED_SPY_OPTION_EXECUTIONS,
)


@dataclass(frozen=True)
class VerifiedDerivativeLedgerCleanupResult:
    changed: bool
    reason: str
    retired_count: int
    retired_intent_ids: tuple[str, ...]
    backup_path: Path | None
    quarantine_path: Path | None
    order_sent: bool = False


class VerifiedDerivativeLedgerCleanupError(ValueError):
    """Raised when exact verified-derivative cleanup cannot proceed safely."""


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        text = raw.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise VerifiedDerivativeLedgerCleanupError(
                f"active ledger line {line_number} is invalid JSON"
            ) from exc
        if not isinstance(row, dict):
            raise VerifiedDerivativeLedgerCleanupError(
                f"active ledger line {line_number} is not an object"
            )
        rows.append(row)
    return rows


def _exec_ids(record: dict) -> tuple[str, ...]:
    raw = record.get("broker_exec_ids")
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(item or "").strip() for item in raw if str(item or "").strip())


def _float(record: dict, key: str) -> float | None:
    try:
        value = float(record.get(key))
    except (TypeError, ValueError):
        return None
    return value


def _exact_evidence_for_record(record: dict):
    if str(record.get("mode", "")).strip().upper() != "IBKR_PAPER":
        return None
    if str(record.get("status", "")).strip().upper() != "FILLED":
        return None
    ids = _exec_ids(record)
    if len(ids) != 1:
        return None
    matches = [item for item in VERIFIED_DERIVATIVE_EXECUTIONS if item.exec_id == ids[0]]
    if len(matches) != 1:
        return None
    evidence = matches[0]
    ticker = str(record.get("ticker", "")).strip().upper()
    side = str(record.get("side", "")).strip().upper()
    shares = _float(record, "shares")
    price = _float(record, "reference_price")
    try:
        broker_order_id = int(record.get("broker_order_id"))
    except (TypeError, ValueError):
        return None
    currency = str(record.get("currency", "")).strip().upper()
    if ticker != evidence.symbol or side != evidence.side:
        return None
    if shares is None or abs(shares - float(evidence.quantity)) > 1e-9:
        return None
    if price is None or abs(price - float(evidence.price)) > 1e-9:
        return None
    if broker_order_id != int(evidence.order_id):
        return None
    if currency and currency != evidence.currency:
        return None
    return evidence


def _broker_has_matching_derivative_position(account: IbkrPaperAccountSnapshot, evidence) -> bool:
    return any(
        str(position.symbol).strip().upper() == evidence.symbol
        and str(position.sec_type).strip().upper() == evidence.sec_type
        and float(position.quantity) != 0.0
        for position in account.positions
    )


def _existing_quarantine_exec_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    result: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        record = payload.get("record")
        if isinstance(record, dict):
            result.update(_exec_ids(record))
    return result


def quarantine_verified_derivative_rows(
    *,
    order_log_path: Path = Path("results/paper_orders.jsonl"),
    quarantine_path: Path = Path("results/quarantined_verified_derivative_ledger_rows.jsonl"),
    backup_dir: Path = Path("results/verified_derivative_cleanup_backups"),
    settings: PlatformSettings = SETTINGS,
    account: IbkrPaperAccountSnapshot | None = None,
) -> VerifiedDerivativeLedgerCleanupResult:
    records = _load_jsonl(order_log_path)
    if not records:
        return VerifiedDerivativeLedgerCleanupResult(
            False, "active ledger is empty; nothing to quarantine", 0, (), None, None
        )

    broker_account = account or preview_ibkr_paper_account_snapshot()
    if not broker_account.ready or broker_account.order_sent:
        raise VerifiedDerivativeLedgerCleanupError(
            "broker Paper account snapshot is not safe enough for derivative-ledger cleanup"
        )

    matched: list[tuple[int, dict, object]] = []
    seen_exec_ids: set[str] = set()
    for index, record in enumerate(records):
        evidence = _exact_evidence_for_record(record)
        if evidence is None:
            continue
        if evidence.exec_id in seen_exec_ids:
            raise VerifiedDerivativeLedgerCleanupError(
                f"duplicate active ledger row for verified exec_id {evidence.exec_id}"
            )
        if _broker_has_matching_derivative_position(broker_account, evidence):
            raise VerifiedDerivativeLedgerCleanupError(
                f"current broker still holds {evidence.sec_type} {evidence.symbol}; refusing cleanup"
            )
        seen_exec_ids.add(evidence.exec_id)
        matched.append((index, record, evidence))

    if not matched:
        return VerifiedDerivativeLedgerCleanupResult(
            False, "no exact verified derivative row is present in the active legacy ledger", 0, (), None, None
        )

    now = account_now(settings)
    stamp = now.strftime("%Y%m%dT%H%M%S%z")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"paper_orders.before_verified_derivative_cleanup.{stamp}.jsonl"
    if backup_path.exists():
        raise VerifiedDerivativeLedgerCleanupError("backup path already exists; refusing overwrite")
    original_text = order_log_path.read_text(encoding="utf-8")
    backup_path.write_text(original_text, encoding="utf-8")

    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    already = _existing_quarantine_exec_ids(quarantine_path)
    with quarantine_path.open("a", encoding="utf-8") as handle:
        for _, record, evidence in matched:
            if evidence.exec_id in already:
                continue
            payload = {
                "quarantined_at": now.isoformat(timespec="seconds"),
                "reason": (
                    "exact broker exec_id/order/side/quantity/price matched immutable verified "
                    "IBKR Paper derivative evidence; current broker derivative position is flat; "
                    "row removed from legacy whole-share accounting only"
                ),
                "verified_security_type": evidence.sec_type,
                "verified_local_symbol": evidence.local_symbol,
                "verified_con_id": evidence.con_id,
                "record": record,
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    matched_indexes = {index for index, _, _ in matched}
    temporary = order_log_path.with_suffix(order_log_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for index, record in enumerate(records):
            if index in matched_indexes:
                continue
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(order_log_path)

    intents = tuple(
        sorted(str(record.get("order_intent_id", "")).strip() for _, record, _ in matched)
    )
    return VerifiedDerivativeLedgerCleanupResult(
        True,
        "verified derivative rows were quarantined from the legacy whole-share ledger without guessing",
        len(matched),
        intents,
        backup_path,
        quarantine_path,
        order_sent=False,
    )
