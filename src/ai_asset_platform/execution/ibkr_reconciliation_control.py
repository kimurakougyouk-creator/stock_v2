from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RECONCILIATION_PAUSE_PATH = Path("data/ibkr_reconciliation_pause.lock")
DEFAULT_RECONCILIATION_EXCLUSION_PATH = Path("data/ibkr_reconciliation_exclusions.jsonl")


class ReconciliationControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconciliationPause:
    path: Path
    owner: str


def acquire_reconciliation_pause(
    owner: str,
    *,
    path: Path = DEFAULT_RECONCILIATION_PAUSE_PATH,
) -> ReconciliationPause:
    normalized = str(owner).strip()
    if not normalized:
        raise ValueError("reconciliation pause owner is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "owner": normalized,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        ensure_ascii=False,
    )
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ReconciliationControlError(
            f"reconciliation safety pause already exists: {path}"
        ) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload + "\n")
    return ReconciliationPause(path=path, owner=normalized)


def release_reconciliation_pause(pause: ReconciliationPause) -> None:
    path = Path(pause.path)
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReconciliationControlError(
            "reconciliation safety pause cannot be verified before release"
        ) from exc
    if str(payload.get("owner", "")).strip() != pause.owner:
        raise ReconciliationControlError(
            "reconciliation safety pause owner changed; refusing release"
        )
    path.unlink()


def reconciliation_is_paused(
    *, path: Path = DEFAULT_RECONCILIATION_PAUSE_PATH
) -> bool:
    return path.exists()


def load_reconciliation_exclusions(
    *, path: Path = DEFAULT_RECONCILIATION_EXCLUSION_PATH
) -> set[str]:
    if not path.exists():
        return set()
    result: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ReconciliationControlError(
                    f"invalid reconciliation exclusion JSON at line {line_number}"
                ) from exc
            if not isinstance(payload, dict):
                raise ReconciliationControlError(
                    f"invalid reconciliation exclusion object at line {line_number}"
                )
            exec_id = str(payload.get("exec_id", "")).strip()
            if not exec_id:
                raise ReconciliationControlError(
                    f"missing exec_id in reconciliation exclusion line {line_number}"
                )
            result.add(exec_id)
    return result


def record_reconciliation_exclusions(
    exec_ids: list[str] | tuple[str, ...] | set[str],
    *,
    symbol: str,
    reason: str,
    order_intent_id: str,
    path: Path = DEFAULT_RECONCILIATION_EXCLUSION_PATH,
) -> tuple[str, ...]:
    normalized_ids = tuple(
        sorted({str(value).strip() for value in exec_ids if str(value).strip()})
    )
    if not normalized_ids:
        raise ReconciliationControlError(
            "at least one broker exec_id is required before reconciliation can resume"
        )
    normalized_symbol = str(symbol).strip().upper()
    normalized_reason = str(reason).strip()
    normalized_intent = str(order_intent_id).strip()
    if not normalized_symbol or not normalized_reason or not normalized_intent:
        raise ValueError("symbol, reason, and order_intent_id are required")

    existing = load_reconciliation_exclusions(path=path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        for exec_id in normalized_ids:
            if exec_id in existing:
                continue
            handle.write(
                json.dumps(
                    {
                        "exec_id": exec_id,
                        "symbol": normalized_symbol,
                        "reason": normalized_reason,
                        "order_intent_id": normalized_intent,
                        "excluded_at": now,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return normalized_ids
