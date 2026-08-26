"""Explicit one-scan entry point for the bounded verified IBKR Paper runtime.

This is the deliberate ordering entry point.  It remains separate from normal
startup, requires an exact operator confirmation plus the IBKR Paper opt-in,
verifies clean broker/local reconciliation first, and refuses Live Trading.
Only the broker-verified universe and quantities owned by ``paper_trading_runner``
can reach execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import os

import paper_trading_runner

from ai_asset_platform.brokers.ibkr_reconciliation_evidence_audit import (
    audit_ibkr_reconciliation_evidence,
)
from ai_asset_platform.core.settings import SETTINGS, PlatformSettings


CONFIRMATION_ENV = "AI_ASSET_VERIFIED_PAPER_RUNTIME_CONFIRM"
CONFIRMATION_VALUE = "RUN_VERIFIED_PAPER_ONLY"


@dataclass(frozen=True)
class VerifiedPaperRuntimeResult:
    ran: bool
    reason: str
    analysis_record_count: int
    confirmed_paper_fill_count: int
    error_count: int
    execution_error_count: int


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


def run_verified_paper_runtime_once(
    *, settings: PlatformSettings = SETTINGS,
) -> VerifiedPaperRuntimeResult:
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
    )


def main() -> int:
    print("===== VERIFIED IBKR PAPER RUNTIME =====")
    print("SCOPE                 : AAPL 1 / SPY 1 / 9432.T 100")
    print("LIVE TRADING          : PROHIBITED")
    try:
        result = run_verified_paper_runtime_once()
    except VerifiedPaperRuntimeError as exc:
        print("RAN                   : False")
        print("REASON                :", str(exc))
        print("CONFIRMED PAPER FILLS : 0")
        print("LIVE ORDER SENT       : False")
        return 2
    except Exception as exc:
        print("RAN                   : False")
        print("REASON                : fail-closed runtime error:", str(exc))
        print("LIVE ORDER SENT       : False")
        return 1

    print("RAN                   :", result.ran)
    print("REASON                :", result.reason)
    print("ANALYSIS RECORDS      :", result.analysis_record_count)
    print("CONFIRMED PAPER FILLS :", result.confirmed_paper_fill_count)
    print("ERROR COUNT           :", result.error_count)
    print("EXECUTION ERROR COUNT :", result.execution_error_count)
    print("LIVE ORDER SENT       : False")
    return 0 if result.error_count == 0 and result.execution_error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
