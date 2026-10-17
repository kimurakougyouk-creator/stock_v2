"""Independent broker-provenance verification for natural Paper strategy fills.

``strategy_profitability_evidence.py`` never connects to a broker: it treats
every local JSONL fill row and the local commission ledger as already-trusted
input, and its own comment is explicit that ``broker_provenance_verified`` may
only become True once a *separate* authenticated broker-provenance mechanism
exists. This module is that separate mechanism.

It independently re-queries the IBKR Paper account for executions,
commissions, and completed orders (reusing the existing, already-tested
read-only collectors in ``ibkr_execution_snapshot.py``,
``ibkr_commission_snapshot.py``, and ``ibkr_completed_order_evidence.py``)
and cross-checks every exec_id referenced by the exact natural-strategy fills
that ``strategy_profitability_evidence`` accounts for. A local ledger that
was hand-edited to look internally consistent cannot pass this check, because
the broker-reported symbol/side/currency/quantity, commission, and the
broker-side order's own ``orderRef`` (set at placement time -- see
``ibkr_paper_order_sender.py``) must independently match.

Read-only throughout. No order is ever created, changed, cancelled, retried,
or transmitted here, and no Live endpoint is ever contacted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable

from ai_asset_platform.brokers.ibkr_commission_snapshot import (
    IbkrPaperCommissionSnapshot,
    preview_ibkr_paper_commission_snapshot,
)
from ai_asset_platform.brokers.ibkr_completed_order_evidence import (
    IbkrCompletedOrderEvidence,
    IbkrPaperCompletedOrderSnapshot,
    preview_ibkr_paper_completed_orders,
)
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
    preview_ibkr_paper_execution_snapshot,
)
from ai_asset_platform.brokers.ibkr_fx_historical import (
    preview_ibkr_paper_historical_fx_rate,
)
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.ibkr_execution_reconcile import (
    _execution_reference_timestamp,
)
from ai_asset_platform.reports.strategy_profitability_evidence import (
    DEFAULT_COMMISSION_REPORT_PATH,
    DEFAULT_ORDER_LOG_PATH,
    StrategyProfitabilityEvidence,
    StrategyProfitabilityEvidenceError,
    _commission_index,
    _load_json_object,
    _load_jsonl,
    _blocked_input_evidence,
    build_strategy_profitability_evidence,
    select_and_dedupe_natural_strategy_fills,
)

# Natural-strategy fills are the only fills this module ever verifies (see
# select_and_dedupe_natural_strategy_fills), and those are recorded only by
# ibkr_signal_runtime.py's synchronous call to legacy_fill_sync.record_confirmed_fill
# immediately after the broker's own execDetails callback -- never by the
# separate, asynchronous broker-recovery reconciliation path. The only
# expected gap between a fill's local created_at and the broker's own
# execution.time is therefore processing latency/clock drift, not a batch
# delay. This bound is generous enough to absorb that latency while still
# rejecting any hour/day-scale tampering relevant to the promotion policy's
# observation-span/evidence-age thresholds.
MAX_LOCAL_VS_BROKER_TIMESTAMP_SKEW_SECONDS = 300.0

FxRateFetcher = Callable[[str, str, float, str], "float | None"]


@dataclass(frozen=True)
class BrokerProvenanceResult:
    verified: bool
    blockers: tuple[str, ...]
    verified_fill_count: int
    total_fill_count: int


def _symbol_for_ticker(ticker: str) -> str:
    normalized = str(ticker).strip().upper()
    return "9432" if normalized == "9432.T" else normalized


def _local_created_at_timestamp(record: dict) -> float | None:
    raw = record.get("created_at")
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


def default_fx_rate_fetcher(
    base_currency: str,
    quote_currency: str,
    reference_timestamp: float,
    end_datetime: str,
    *,
    timeout: float = 10.0,
) -> float | None:
    """Independently resolve a broker historical FX rate near a fill's exec time.

    Reuses the existing read-only ``preview_ibkr_paper_historical_fx_rate``
    collector (already used by the natural-strategy reconciliation path in
    ``ibkr_execution_reconcile.py``) instead of inventing a new FX source.
    """
    evidence = preview_ibkr_paper_historical_fx_rate(
        base_currency=base_currency,
        quote_currency=quote_currency,
        end_datetime=end_datetime,
        reference_timestamp=reference_timestamp,
        timeout=timeout,
    )
    if evidence.ready and evidence.rate is not None and float(evidence.rate) > 0:
        return float(evidence.rate)
    return None


def verify_broker_provenance_for_strategy_fills(
    strategy_fills: Iterable[dict],
    *,
    execution_snapshot: IbkrPaperExecutionSnapshot,
    commission_snapshot: IbkrPaperCommissionSnapshot,
    completed_order_snapshot: IbkrPaperCompletedOrderSnapshot,
    local_commission_report: dict | None,
    account_currency: str,
    fx_rate_fetcher: FxRateFetcher,
) -> BrokerProvenanceResult:
    """Cross-check local natural-strategy fills against independent broker evidence.

    Every ``broker_exec_fills`` row on every fill must match exactly one
    broker execution row (same symbol/side/currency/quantity, STK only) that
    also carries exactly one broker commission row in the same currency and
    amount as the local commission ledger entry for that exec_id, and whose
    local ``created_at`` is within
    ``MAX_LOCAL_VS_BROKER_TIMESTAMP_SKEW_SECONDS`` of the broker's own
    execution time. The matched quantities must sum to the fill's full share
    count, the broker's quantity-weighted average execution price must equal
    the fill's local ``reference_price`` exactly, and, for any fill whose
    currency differs from ``account_currency``, the local
    ``fx_to_account_rate`` must equal an independently fetched broker
    historical FX rate exactly. Every matched execution's broker-side order
    must also carry an ``orderRef`` (IBKR's immutable, broker-persisted field,
    set at order placement -- see ``ibkr_paper_order_sender.py``) equal to the
    fill's own ``order_intent_id``. Missing, mismatched, or conflicting
    evidence fails closed; nothing is guessed, back-filled, or
    tolerance-rounded (other than the bounded, justified clock-skew tolerance
    above).

    Checking identity (symbol/side/currency/quantity) alone is not enough: a
    local fill whose ``reference_price``, commission amount, timestamp, or FX
    rate was edited after the fact would still carry a matching exec_id and
    would otherwise pass unnoticed, silently corrupting the net-PnL evidence
    (and the promotion policy's time-based thresholds) this provenance check
    exists to protect. Nor is matching every field alone enough: without the
    ``orderRef`` check, an entirely unrelated real Paper trade could be
    relabeled locally with a ``signal-runner:`` intent and would pass this
    check as long as its own true symbol/side/currency/quantity/price/
    timestamp/commission happened to be copied correctly, since none of those
    fields say anything about *why* the order was placed.
    """
    normalized_account_currency = str(account_currency).strip().upper()
    fills = [record for record in strategy_fills if isinstance(record, dict)]
    blockers: list[str] = []

    if not execution_snapshot.ready:
        blockers.append("Paper execution snapshot is not ready")
    if not commission_snapshot.ready:
        blockers.append("Paper commission snapshot is not ready")
    if not completed_order_snapshot.ready:
        blockers.append("Paper completed-order snapshot is not ready")
    if blockers:
        return BrokerProvenanceResult(False, tuple(blockers), 0, len(fills))
    if not fills:
        return BrokerProvenanceResult(
            False, ("no natural strategy fills were supplied",), 0, 0
        )

    try:
        if local_commission_report is None:
            raise StrategyProfitabilityEvidenceError(
                "no local commission ledger was supplied"
            )
        local_commissions = _commission_index(local_commission_report)
    except StrategyProfitabilityEvidenceError as exc:
        return BrokerProvenanceResult(
            False,
            (
                "local commission ledger is unreadable; cannot verify broker "
                f"commission amounts: {exc}",
            ),
            0,
            len(fills),
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
    completed_orders_by_perm_id: dict[int, IbkrCompletedOrderEvidence] = {}
    for row in completed_order_snapshot.orders:
        previous = completed_orders_by_perm_id.get(row.perm_id)
        if previous is not None and previous != row:
            blockers.append(f"conflicting broker completed-order rows for perm_id={row.perm_id}")
            continue
        completed_orders_by_perm_id[row.perm_id] = row

    verified_fill_count = 0
    for position, record in enumerate(fills, start=1):
        ticker = str(record.get("ticker", "")).strip().upper()
        side = str(record.get("side", "")).strip().upper()
        currency = str(record.get("currency", "")).strip().upper()
        order_intent_id = str(record.get("order_intent_id", "")).strip()
        if not order_intent_id:
            blockers.append(f"strategy fill #{position} is missing order_intent_id")
            continue
        try:
            shares = Decimal(str(int(record.get("shares"))))
        except (TypeError, ValueError):
            blockers.append(f"strategy fill #{position} has invalid shares")
            continue
        try:
            reference_price = Decimal(str(record.get("reference_price")))
        except InvalidOperation:
            blockers.append(f"strategy fill #{position} has an invalid reference_price")
            continue
        local_created_at_epoch = _local_created_at_timestamp(record)
        if local_created_at_epoch is None:
            blockers.append(
                f"strategy fill #{position} is missing a valid timezone-aware created_at"
            )
            continue

        raw_exec_fills = record.get("broker_exec_fills")
        if not isinstance(raw_exec_fills, list) or not raw_exec_fills:
            blockers.append(f"strategy fill #{position} is missing broker_exec_fills")
            continue

        symbol = _symbol_for_ticker(ticker)
        matched_total = Decimal("0")
        matched_price_times_quantity = Decimal("0")
        first_execution_time: str | None = None
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
            broker_execution_epoch = _execution_reference_timestamp(execution.time)
            if broker_execution_epoch is None:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} has an unparseable "
                    "broker execution time"
                )
                continue
            if (
                abs(local_created_at_epoch - broker_execution_epoch)
                > MAX_LOCAL_VS_BROKER_TIMESTAMP_SKEW_SECONDS
            ):
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} local created_at does "
                    "not match the broker execution time within tolerance"
                )
                continue
            if first_execution_time is None:
                first_execution_time = execution.time
            completed_order = completed_orders_by_perm_id.get(execution.perm_id)
            if completed_order is None:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} has no matching "
                    "broker completed-order evidence to verify its order_intent_id"
                )
                continue
            broker_order_ref = str(completed_order.order_ref or "").strip()
            if not broker_order_ref or broker_order_ref != order_intent_id:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} broker order "
                    "orderRef does not match the local order_intent_id"
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
            local_commission = local_commissions.get(exec_id)
            if local_commission is None:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} has no local "
                    "commission ledger entry to cross-check"
                )
                continue
            local_commission_amount, local_commission_currency = local_commission
            try:
                broker_commission_amount = Decimal(str(commission.commission))
            except InvalidOperation:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} has a non-finite "
                    "broker commission amount"
                )
                continue
            if (
                local_commission_currency != currency
                or broker_commission_amount != local_commission_amount
            ):
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} broker commission "
                    "amount does not match the local commission ledger"
                )
                continue
            try:
                local_shares = Decimal(str(raw_fill.get("shares")))
                broker_shares = Decimal(str(execution.quantity))
                broker_price = Decimal(str(execution.price))
            except InvalidOperation:
                fill_blocked = True
                blockers.append(
                    f"strategy fill #{position} exec_id={exec_id} has a non-finite "
                    "share quantity or price"
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
            matched_price_times_quantity += local_shares * broker_price

        if fill_blocked:
            continue
        if matched_total != shares:
            blockers.append(
                f"strategy fill #{position} matched broker quantity does not equal "
                "the total fill shares"
            )
            continue
        weighted_average_price = matched_price_times_quantity / matched_total
        if weighted_average_price != reference_price:
            blockers.append(
                f"strategy fill #{position} broker quantity-weighted average execution "
                "price does not match the local reference_price"
            )
            continue

        if currency != normalized_account_currency:
            raw_fx_rate = record.get("fx_to_account_rate")
            try:
                local_fx_rate = Decimal(str(raw_fx_rate))
            except InvalidOperation:
                blockers.append(
                    f"strategy fill #{position} has an invalid fx_to_account_rate "
                    "for a foreign-currency fill"
                )
                continue
            assert first_execution_time is not None  # guaranteed by matched_total == shares
            reference_epoch = _execution_reference_timestamp(first_execution_time)
            if reference_epoch is None:
                blockers.append(
                    f"strategy fill #{position} has no parseable broker execution "
                    "time to anchor an independent FX check"
                )
                continue
            broker_fx_rate = fx_rate_fetcher(
                currency, normalized_account_currency, reference_epoch, first_execution_time
            )
            if broker_fx_rate is None:
                blockers.append(
                    f"strategy fill #{position} independent broker FX evidence for "
                    f"{currency}->{normalized_account_currency} near the fill time "
                    "is unavailable"
                )
                continue
            try:
                broker_fx_rate_decimal = Decimal(str(broker_fx_rate))
            except InvalidOperation:
                blockers.append(
                    f"strategy fill #{position} broker FX rate is non-finite"
                )
                continue
            if broker_fx_rate_decimal != local_fx_rate:
                blockers.append(
                    f"strategy fill #{position} local fx_to_account_rate does not "
                    "match the independently fetched broker FX rate"
                )
                continue

        verified_fill_count += 1

    verified = not blockers and verified_fill_count == len(fills)
    return BrokerProvenanceResult(verified, tuple(blockers), verified_fill_count, len(fills))


def collect_and_verify_broker_provenance(
    strategy_fills: Iterable[dict],
    *,
    local_commission_report: dict | None,
    account_currency: str | None = None,
    timeout: float = 10.0,
) -> BrokerProvenanceResult:
    """Connect to the Paper broker and verify the supplied natural strategy fills.

    This is the only function in this module that opens a broker socket
    unconditionally. It never creates, changes, cancels, retries, or
    transmits an order, and it never contacts a Live endpoint (the underlying
    collectors are hardcoded to the Paper gateway/TWS ports). For any
    foreign-currency fill, ``verify_broker_provenance_for_strategy_fills``
    opens one additional read-only historical-FX socket per fill via the
    injected ``fx_rate_fetcher``.
    """
    normalized_account_currency = str(account_currency or SETTINGS.account_currency)
    execution_snapshot = preview_ibkr_paper_execution_snapshot(timeout=timeout)
    commission_snapshot = preview_ibkr_paper_commission_snapshot(timeout=timeout)
    completed_order_snapshot = preview_ibkr_paper_completed_orders(timeout=timeout)

    def _fetch_fx_rate(
        base_currency: str,
        quote_currency: str,
        reference_timestamp: float,
        end_datetime: str,
    ) -> float | None:
        return default_fx_rate_fetcher(
            base_currency,
            quote_currency,
            reference_timestamp,
            end_datetime,
            timeout=timeout,
        )

    return verify_broker_provenance_for_strategy_fills(
        strategy_fills,
        execution_snapshot=execution_snapshot,
        commission_snapshot=commission_snapshot,
        completed_order_snapshot=completed_order_snapshot,
        local_commission_report=local_commission_report,
        account_currency=normalized_account_currency,
        fx_rate_fetcher=_fetch_fx_rate,
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
        collect_and_verify_broker_provenance(
            provenance_fills,
            local_commission_report=commission_report,
            account_currency=account,
            timeout=timeout,
        )
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
