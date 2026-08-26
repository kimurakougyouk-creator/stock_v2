"""Explicit one-scan entry point for the bounded verified IBKR Paper runtime.

This is the deliberate ordering entry point.  It remains separate from normal
startup, requires an exact operator confirmation plus the IBKR Paper opt-in,
verifies clean broker/local reconciliation first, and refuses Live Trading.
Only the broker-verified universe and quantities owned by ``paper_trading_runner``
can reach execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

import paper_trading_runner

from ai_asset_platform.brokers.ibkr_reconciliation_evidence_audit import (
    audit_ibkr_reconciliation_evidence,
)
from ai_asset_platform.core.settings import SETTINGS, PlatformSettings
from ai_asset_platform.core.account_clock import account_now


CONFIRMATION_ENV = "AI_ASSET_VERIFIED_PAPER_RUNTIME_CONFIRM"
CONFIRMATION_VALUE = "RUN_VERIFIED_PAPER_ONLY"
RUNTIME_REPORT_SCHEMA_VERSION = 1
DEFAULT_RUNTIME_REPORT_PATH = Path(
    "results/ibkr_verified_paper_runtime_latest.json"
)
DEFAULT_RUNTIME_HISTORY_PATH = Path(
    "results/ibkr_verified_paper_runtime_history.jsonl"
)
VERIFIED_SCOPE = {"AAPL": 1, "SPY": 1, "9432.T": 100}


@dataclass(frozen=True)
class VerifiedPaperRuntimeResult:
    ran: bool
    reason: str
    analysis_record_count: int
    confirmed_paper_fill_count: int
    error_count: int
    execution_error_count: int
    started_at: str
    completed_at: str
    final_decisions: tuple[dict, ...] = ()


class VerifiedPaperRuntimeError(RuntimeError):
    """Raised when the deliberate Paper runtime must fail closed."""


def _require_safety_gates(settings: PlatformSettings) -> None:
    if os.getenv(CONFIRMATION_ENV, "").strip() != CONFIRMATION_VALUE:
        raise VerifiedPaperRuntimeError(
            "exact verified Paper runtime confirmation is missing"
        )
    if not settings.enable_paper_trading:
        raise VerifiedPaperRuntimeError("Paper Trading is disabled")
    if not settings.enable_ibkr_paper:
        raise VerifiedPaperRuntimeError("IBKR Paper opt-in is disabled")
    if settings.enable_live_trading or settings.live_trading_unlocked:
        raise VerifiedPaperRuntimeError("Live Trading safety lock is not intact")


def _timestamp() -> str:
    return account_now().isoformat(timespec="seconds")


def _json_scalar(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return str(value)


def _final_decisions(records: list[dict]) -> tuple[dict, ...]:
    decisions: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        decisions.append(
            {
                "ticker": str(record.get("Ticker", "")).strip().upper(),
                "technical_signal": str(
                    record.get("Signal", "HOLD")
                ).strip().upper(),
                "ai_signal": str(record.get("AISignal", "HOLD")).strip().upper(),
                "final_signal": str(
                    record.get("FinalSignal", "HOLD")
                ).strip().upper(),
                "close": _json_scalar(record.get("Close")),
                "ai_provider": str(record.get("AIProvider", "") or ""),
                "ai_available": bool(record.get("AIAvailable", False)),
            }
        )
    return tuple(decisions)


def runtime_result_record(result: VerifiedPaperRuntimeResult) -> dict:
    return {
        "schema_version": RUNTIME_REPORT_SCHEMA_VERSION,
        "status": "SUCCESS"
        if result.error_count == 0 and result.execution_error_count == 0
        else "ERROR",
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "scope": dict(VERIFIED_SCOPE),
        "ran": result.ran,
        "reason": result.reason,
        "analysis_record_count": result.analysis_record_count,
        "confirmed_paper_fill_count": result.confirmed_paper_fill_count,
        "error_count": result.error_count,
        "execution_error_count": result.execution_error_count,
        "final_decisions": list(result.final_decisions),
        "live_trading": "PROHIBITED",
        "live_order_sent": False,
    }


def runtime_failure_record(
    *, status: str, reason: str, started_at: str, completed_at: str
) -> dict:
    return {
        "schema_version": RUNTIME_REPORT_SCHEMA_VERSION,
        "status": str(status).strip().upper(),
        "started_at": started_at,
        "completed_at": completed_at,
        "scope": dict(VERIFIED_SCOPE),
        "ran": False,
        "reason": str(reason),
        "analysis_record_count": 0,
        "confirmed_paper_fill_count": 0,
        "error_count": 1,
        "execution_error_count": 0,
        "final_decisions": [],
        "live_trading": "PROHIBITED",
        "live_order_sent": False,
    }


def persist_runtime_record(
    record: dict,
    *,
    latest_path: Path = DEFAULT_RUNTIME_REPORT_PATH,
    history_path: Path = DEFAULT_RUNTIME_HISTORY_PATH,
) -> None:
    """Atomically replace latest status and append one durable history row."""
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
    temporary = latest_path.with_suffix(latest_path.suffix + ".tmp")
    temporary.write_text(serialized + "\n", encoding="utf-8")
    temporary.replace(latest_path)
    with history_path.open("a", encoding="utf-8") as history:
        history.write(serialized + "\n")


def run_verified_paper_runtime_once(
    *, settings: PlatformSettings = SETTINGS,
) -> VerifiedPaperRuntimeResult:
    started_at = _timestamp()
    _require_safety_gates(settings)
    audit = audit_ibkr_reconciliation_evidence()
    if audit.order_sent:
        raise VerifiedPaperRuntimeError(
            "reconciliation audit unexpectedly reported an order"
        )
    if not audit.account_ready or not audit.execution_snapshot_ready:
        raise VerifiedPaperRuntimeError(
            "broker account or execution snapshot is not ready"
        )
    if audit.blockers or audit.next_action != "RECONCILIATION_EVIDENCE_IS_CLEAN":
        raise VerifiedPaperRuntimeError(
            f"reconciliation is not clean: {audit.next_action}"
        )

    result = paper_trading_runner.run_paper_trading()
    records = list(result.get("records") or [])
    paper_orders = list(result.get("paper_orders") or [])
    errors = list(result.get("errors") or [])
    execution_errors = list(result.get("execution_errors") or [])
    reason = (
        "verified Paper scan completed"
        if not errors
        else "verified Paper scan completed with fail-closed errors"
    )
    return VerifiedPaperRuntimeResult(
        ran=True,
        reason=reason,
        analysis_record_count=len(records),
        confirmed_paper_fill_count=len(paper_orders),
        error_count=len(errors),
        execution_error_count=len(execution_errors),
        started_at=started_at,
        completed_at=_timestamp(),
        final_decisions=_final_decisions(records),
    )


def main() -> int:
    print("===== VERIFIED IBKR PAPER RUNTIME =====")
    print("SCOPE                 : AAPL 1 / SPY 1 / 9432.T 100")
    print("LIVE TRADING          : PROHIBITED")
    started_at = _timestamp()
    try:
        result = run_verified_paper_runtime_once()
    except VerifiedPaperRuntimeError as exc:
        failure = runtime_failure_record(
            status="BLOCKED",
            reason=str(exc),
            started_at=started_at,
            completed_at=_timestamp(),
        )
        try:
            persist_runtime_record(failure)
        except Exception as report_error:
            print("MONITORING REPORT ERROR:", str(report_error))
        print("RAN                   : False")
        print("REASON                :", str(exc))
        print("CONFIRMED PAPER FILLS : 0")
        print("LIVE ORDER SENT       : False")
        return 2
    except Exception as exc:
        failure = runtime_failure_record(
            status="ERROR",
            reason=f"fail-closed runtime error: {exc}",
            started_at=started_at,
            completed_at=_timestamp(),
        )
        try:
            persist_runtime_record(failure)
        except Exception as report_error:
            print("MONITORING REPORT ERROR:", str(report_error))
        print("RAN                   : False")
        print("REASON                : fail-closed runtime error:", str(exc))
        print("LIVE ORDER SENT       : False")
        return 1

    try:
        persist_runtime_record(runtime_result_record(result))
    except Exception as exc:
        print("RAN                   :", result.ran)
        print("REASON                : runtime completed but monitoring report failed:", str(exc))
        print("CONFIRMED PAPER FILLS :", result.confirmed_paper_fill_count)
        print("LIVE ORDER SENT       : False")
        return 1

    print("RAN                   :", result.ran)
    print("REASON                :", result.reason)
    print("ANALYSIS RECORDS      :", result.analysis_record_count)
    print("CONFIRMED PAPER FILLS :", result.confirmed_paper_fill_count)
    print("ERROR COUNT           :", result.error_count)
    print("EXECUTION ERROR COUNT :", result.execution_error_count)
    print("MONITORING REPORT     :", DEFAULT_RUNTIME_REPORT_PATH)
    print("MONITORING HISTORY    :", DEFAULT_RUNTIME_HISTORY_PATH)
    print("LIVE ORDER SENT       : False")
    return 0 if result.error_count == 0 and result.execution_error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
