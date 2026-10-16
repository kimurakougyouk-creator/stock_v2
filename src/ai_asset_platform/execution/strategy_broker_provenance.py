"""Independent broker-provenance verification for natural Paper strategy fills.

``strategy_profitability_evidence.py`` never connects to a broker: it treats
every local JSONL fill row and the local commission ledger as already-trusted
input, and its own comment is explicit that ``broker_provenance_verified`` may
only become True once a *separate* authenticated broker-provenance mechanism
exists. This module is that separate mechanism.

It independently re-queries the IBKR Paper account for executions and
commissions (reusing the existing, already-tested read-only collectors in
``ibkr_execution_snapshot.py`` and ``ibkr_commission_snapshot.py``) and cross-
checks every exec_id referenced by the exact natural-strategy fills that
``strategy_profitability_evidence`` accounts for. A local ledger that was
hand-edited to look internally consistent cannot pass this check, because the
broker-reported symbol/side/currency/quantity and the broker-reported
commission must independently match.

Read-only throughout. No order is ever created, changed, cancelled, retried,
or transmitted here, and no Live endpoint is ever contacted.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from ai_asset_platform.brokers.ibkr_commission_snapshot import (
    IbkrPaperCommissionSnapshot,
    preview_ibkr_paper_commission_snapshot,
)
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
    preview_ibkr_paper_execution_snapshot,
)
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.reports.strategy_profitability_evidence import (
    DEFAULT_COMMISSION_REPORT_PATH,
    DEFAULT_ORDER_LOG_PATH,
    StrategyProfitabilityEvidence,
    StrategyProfitabilityEvidenceError,
    _load_json_object,
    _load_jsonl,
    _blocked_input_evidence,
    build_strategy_profitability_evidence,
    select_and_dedupe_natural_strategy_fills,
)


@dataclass(frozen=True)
class BrokerProvenanceResult:
    verified: bool
    blockers: tuple[str, ...]
    verified_fill_count: int
    total_fill_count: int


def _symbol_for_ticker(ticker: str) -> str:
    normalized = str(ticker).strip().upper()
    return "9432" if normalized == "9432.T" else normalized


def verify_broker_provenance_for_strategy_fills(
    strategy_fills: Iterable[dict],
    *,
    execution_snapshot: IbkrPaperExecutionSnapshot,
    commission_snapshot: IbkrPaperCommissionSnapshot,
) -> BrokerProvenanceResult:
    """Cross-check local natural-strategy fills against independent broker evidence.

    Every ``broker_exec_fills`` row on every fill must match exactly one
    broker execution row (same symbol/side/currency/quantity, STK only) that
    also carries exactly one broker commission row in the same currency, and
    the matched quantities must sum to the fill's full share count. Missing,
    mismatched, or conflicting evidence fails closed; nothing is guessed or
    back-filled.
    """
    fills = [record for record in strategy_fills if isinstance(record, dict)]
    blockers: list[str] = []

    if not execution_snapshot.ready:
        blockers.append("Paper execution snapshot is not ready")
    if not commission_snapshot.ready:
        blockers.append("Paper commission snapshot is not ready")
    if blockers:
        return BrokerProvenanceResult(False, tuple(blockers), 0, len(fills))
    if not fills:
        return BrokerProvenanceResult(
            False, ("no natural strategy fills were supplied",), 0, 0
        )

    executions_by_id: dict[str, IbkrExecutionEvidence] = {}
    for row in execution_snapshot.executions:
        exec_id = str(row.exec_id or "").strip()
        if not exec_id:
            continue
        previous = executions_by_id.get(exec_id)
        if previous is not None and previous != row:
            blockers.append(f"conflicting broker execution rows for exec_id={exec_id}")
            continue
        executions_by_id[exec_id] = row
    commissions_by_id = {row.exec_id: row for row in commission_snapshot.commissions}

    verified_fill_count = 0
    for position, record in enumerate(fills, start=1):
        ticker = str(record.get("ticker", "")).strip().upper()
        side = str(record.get("side", "")).strip().upper()
        currency = str(record.get("currency", "")).strip().upper()
        try:
            shares = Decimal(str(int(record.get("shares"))))
        except (TypeError, ValueError):
            blockers.append(f"strategy fill #{position} has invalid shares")
            continue

        raw_exec_fills = record.get("broker_exec_fills")
        if not isinstance(raw_exec_fills, list) or not raw_exec_fills:
            blockers.append(f"strategy fill #{position} is missing broker_exec_fills")
            continue

        symbol = _symbol_for_ticker(ticker)
        matched_total = Decimal("0")
        fill_blocked = False
        for raw_fill in raw_exec_fills:
            if not isinstance(raw_fill, dict):
                fill_blocked = True
                blockers.append(f"strategy fill #{position} has an invalid execution row")
                continue
            exec_id = str(raw_fill.get("exec_id", "")).strip()
            execution = executions_by_id.get(exec_id)
            if execution is None:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} was not found in the "
                    "broker execution snapshot"
                )
                continue
            if (
                execution.symbol != symbol
                or execution.side != side
                or execution.currency != currency
                or execution.sec_type != "STK"
            ):
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} broker execution identity "
                    "does not match the local fill"
                )
                continue
            commission = commissions_by_id.get(exec_id)
            if commission is None:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} is missing broker "
                    "commission evidence"
                )
                continue
            if commission.currency != currency:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} broker commission "
                    "currency does not match the fill"
                )
                continue
            try:
                local_shares = Decimal(str(raw_fill.get("shares")))
                broker_shares = Decimal(str(execution.quantity))
            except InvalidOperation:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} has a non-finite "
                    "share quantity"
                )
                continue
            if broker_shares != local_shares:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} broker quantity does "
                    "not match the local quantity"
                )
                continue
            matched_total += local_shares

        if fill_blocked:
            continue
        if matched_total != shares:
            blockers.append(
                f"strategy fill #{position} matched broker quantity does not equal "
                "the total fill shares"
            )
            continue
        verified_fill_count += 1

    verified = not blockers and verified_fill_count == len(fills)
    return BrokerProvenanceResult(verified, tuple(blockers), verified_fill_count, len(fills))


def collect_and_verify_broker_provenance(
    strategy_fills: Iterable[dict],
    *,
    timeout: float = 10.0,
) -> BrokerProvenanceResult:
    """Connect to the Paper broker and verify the supplied natural strategy fills.

    This is the only function in this module that opens a broker socket. It
    never creates, changes, cancels, retries, or transmits an order, and it
    never contacts a Live endpoint (the underlying collectors are hardcoded
    to the Paper gateway/TWS ports).
    """
    execution_snapshot = preview_ibkr_paper_execution_snapshot(timeout=timeout)
    commission_snapshot = preview_ibkr_paper_commission_snapshot(timeout=timeout)
    return verify_broker_provenance_for_strategy_fills(
        strategy_fills,
        execution_snapshot=execution_snapshot,
        commission_snapshot=commission_snapshot,
    )


def audit_strategy_profitability_evidence_with_broker_provenance(
    *,
    order_log_path: Path = DEFAULT_ORDER_LOG_PATH,
    commission_report_path: Path = DEFAULT_COMMISSION_REPORT_PATH,
    account_currency: str | None = None,
    timeout: float = 10.0,
) -> tuple[StrategyProfitabilityEvidence, BrokerProvenanceResult | None]:
    """Build the Phase 5 profitability report with real broker-provenance evidence.

    Returns the same ``StrategyProfitabilityEvidence`` as
    ``audit_strategy_profitability_evidence``, except ``broker_provenance_verified``
    is a genuinely computed value instead of a hardcoded False, plus the
    ``BrokerProvenanceResult`` used to compute it (``None`` only when there are
    no natural strategy fills to check, in which case the evidence report
    itself already fails closed with no net-fee claim to verify).
    """
    account = str(account_currency or SETTINGS.account_currency)
    try:
        records = _load_jsonl(order_log_path)
        commission_report = _load_json_object(commission_report_path)
    except (StrategyProfitabilityEvidenceError, UnicodeError, OSError) as exc:
        return (
            _blocked_input_evidence(
                reason=f"Profitability source evidence is unreadable; report blocked: {exc}",
                account_currency=account,
            ),
            None,
        )

    try:
        provenance_fills = select_and_dedupe_natural_strategy_fills(records)
    except StrategyProfitabilityEvidenceError:
        provenance_fills = []

    provenance = (
        collect_and_verify_broker_provenance(provenance_fills, timeout=timeout)
        if provenance_fills
        else None
    )
    evidence = build_strategy_profitability_evidence(
        records,
        account_currency=account,
        commission_report=commission_report,
        broker_provenance_verified=bool(provenance and provenance.verified),
    )
    return evidence, provenance


def main() -> int:
    evidence, provenance = audit_strategy_profitability_evidence_with_broker_provenance()
    print("===== STRATEGY PROFITABILITY EVIDENCE (BROKER-VERIFIED) =====")
    print("EVIDENCE STATUS            :", evidence.evidence_status)
    print("STRATEGY FILLS             :", evidence.strategy_fill_count)
    print("BROKER PROVENANCE VERIFIED :", evidence.broker_provenance_verified)
    if provenance is not None:
        print("PROVENANCE VERIFIED FILLS  :", f"{provenance.verified_fill_count}/{provenance.total_fill_count}")
        for blocker in provenance.blockers:
            print("PROVENANCE BLOCKER         :", blocker)
    print("ORDER SENT                 : False")
    print("LIVE TRADING                : PROHIBITED")
    return 0 if evidence.broker_provenance_verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
