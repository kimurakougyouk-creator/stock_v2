"""Persist exact closed-SPY FX evidence into the durable Paper ledger.

The historical one-share SPY BUY is missing account-currency FX, while its
exact one-share closing SELL has an explicit broker-captured FX rate.  This
repair copies only that explicit SELL rate into the BUY row after requiring
distinct broker execution identities and flat broker/local SPY positions.
The original ledger is backed up before an atomic replacement.  No broker order
is created, changed, cancelled, or transmitted.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.core.account_clock import account_now
from ai_asset_platform.core.settings import PlatformSettings, SETTINGS
from ai_asset_platform.reports.paired_spy_close_accounting import (
    PairedSpyCloseAccountingError,
    enrich_closed_spy_round_trip,
)


@dataclass(frozen=True)
class ClosedSpyFxLedgerRepairResult:
    changed: bool
    reason: str
    repaired_intent_id: str | None
    fx_to_account_rate: float | None
    reference_exec_ids: tuple[str, ...]
    backup_path: Path | None
    order_sent: bool = False


class ClosedSpyFxLedgerRepairError(ValueError):
    """Raised when durable SPY FX repair cannot be proven safe."""


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8", errors="strict").splitlines(), 1
    ):
        text = raw.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClosedSpyFxLedgerRepairError(
                f"active ledger line {line_number} is invalid JSON"
            ) from exc
        if not isinstance(row, dict):
            raise ClosedSpyFxLedgerRepairError(
                f"active ledger line {line_number} is not an object"
            )
        rows.append(row)
    return rows


def _exec_ids(record: dict) -> tuple[str, ...]:
    raw = record.get("broker_exec_ids")
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(
        str(item or "").strip()
        for item in raw
        if str(item or "").strip()
    )


def _is_spy_fill(record: dict, side: str) -> bool:
    return (
        str(record.get("mode", "")).strip().upper() == "IBKR_PAPER"
        and str(record.get("status", "")).strip().upper() == "FILLED"
        and str(record.get("ticker", "")).strip().upper() == "SPY"
        and str(record.get("side", "")).strip().upper() == side
    )


def _local_spy_quantity(records: list[dict]) -> int:
    held = 0
    for row in records:
        if not (_is_spy_fill(row, "BUY") or _is_spy_fill(row, "SELL")):
            continue
        try:
            shares = int(row.get("shares"))
        except (TypeError, ValueError) as exc:
            raise ClosedSpyFxLedgerRepairError(
                "SPY ledger quantity is not a whole number"
            ) from exc
        if shares <= 0:
            raise ClosedSpyFxLedgerRepairError("SPY ledger quantity is not positive")
        if str(row.get("side", "")).strip().upper() == "BUY":
            held += shares
        else:
            if shares > held:
                raise ClosedSpyFxLedgerRepairError(
                    "SPY ledger contains a SELL larger than confirmed holdings"
                )
            held -= shares
    return held


def repair_closed_spy_buy_fx(
    *,
    order_log_path: Path = Path("results/paper_orders.jsonl"),
    backup_dir: Path = Path("results/closed_spy_fx_repair_backups"),
    settings: PlatformSettings = SETTINGS,
    account: IbkrPaperAccountSnapshot | None = None,
) -> ClosedSpyFxLedgerRepairResult:
    records = _load_jsonl(order_log_path)
    if not records:
        return ClosedSpyFxLedgerRepairResult(
            False, "active ledger is empty; nothing to repair", None, None, (), None
        )

    broker_account = account or preview_ibkr_paper_account_snapshot()
    if not broker_account.ready or broker_account.order_sent:
        raise ClosedSpyFxLedgerRepairError(
            "broker Paper account snapshot is not safe enough for SPY FX repair"
        )
    if str(broker_account.base_currency).strip().upper() != str(
        settings.account_currency
    ).strip().upper():
        raise ClosedSpyFxLedgerRepairError(
            "broker base currency does not match configured account currency"
        )
    broker_spy = sum(
        float(position.quantity)
        for position in broker_account.positions
        if str(position.symbol).strip().upper() == "SPY"
    )
    if abs(broker_spy) > 1e-9:
        raise ClosedSpyFxLedgerRepairError(
            f"current broker SPY quantity is {broker_spy:g}; refusing repair"
        )
    local_spy = _local_spy_quantity(records)
    if local_spy != 0:
        raise ClosedSpyFxLedgerRepairError(
            f"current local SPY quantity is {local_spy}; refusing repair"
        )

    try:
        enriched = enrich_closed_spy_round_trip(records)
    except PairedSpyCloseAccountingError as exc:
        raise ClosedSpyFxLedgerRepairError(str(exc)) from exc

    changed_indexes = [
        index
        for index, (before, after) in enumerate(zip(records, enriched, strict=True))
        if before.get("fx_to_account_rate") in (None, "")
        and after.get("fx_to_account_rate") not in (None, "")
    ]
    if not changed_indexes:
        return ClosedSpyFxLedgerRepairResult(
            False,
            "no unique closed SPY BUY requires explicit SELL FX evidence",
            None,
            None,
            (),
            None,
        )
    if len(changed_indexes) != 1:
        raise ClosedSpyFxLedgerRepairError(
            "closed SPY FX repair did not resolve to exactly one BUY row"
        )

    buy_index = changed_indexes[0]
    buy = records[buy_index]
    if not _is_spy_fill(buy, "BUY"):
        raise ClosedSpyFxLedgerRepairError("eligible FX repair row is not a SPY BUY")
    sells = [row for row in records if _is_spy_fill(row, "SELL")]
    if len(sells) != 1:
        raise ClosedSpyFxLedgerRepairError(
            "closed SPY FX repair requires exactly one matching SELL"
        )
    sell_ids = _exec_ids(sells[0])
    if not sell_ids:
        raise ClosedSpyFxLedgerRepairError(
            "matching SPY SELL has no broker execution identity"
        )

    now = account_now(settings)
    repaired = enriched[buy_index]
    repaired["fx_accounting_reference_exec_ids"] = list(sell_ids)
    repaired["fx_accounting_repaired_at"] = now.isoformat(timespec="seconds")

    stamp = now.strftime("%Y%m%dT%H%M%S%z")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"paper_orders.before_closed_spy_fx_repair.{stamp}.jsonl"
    if backup_path.exists():
        raise ClosedSpyFxLedgerRepairError("backup path already exists; refusing overwrite")
    original_text = order_log_path.read_text(encoding="utf-8")
    backup_path.write_text(original_text, encoding="utf-8")

    temporary = order_log_path.with_suffix(order_log_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in enriched:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(order_log_path)

    return ClosedSpyFxLedgerRepairResult(
        True,
        "exact closed SPY SELL FX was persisted into the matching BUY without guessing",
        str(repaired.get("order_intent_id", "")).strip() or None,
        float(repaired["fx_to_account_rate"]),
        sell_ids,
        backup_path,
        order_sent=False,
    )
