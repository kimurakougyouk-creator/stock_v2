"""Read-only profitability evidence for natural verified IBKR Paper strategy fills.

Natural strategy fills are identified from the durable order-intent structure
actually emitted by ``signal_runner._build_signal_order_intent_id``:
``signal-runner:<ticker>:<BUY|SELL>:<quantity>:<bar-key>``.

The identity is validated against the fill record itself so deliberate proof,
reset, recovery, derivative, and legacy local Paper rows are not silently mixed
into strategy-performance metrics. Older ``signal-runner:paper-pilot:...`` proof
identifiers do not match the natural runtime structure and are excluded.

This module never connects to a broker and never creates, changes, cancels, or
transmits an order. Gross PnL is always computed from durable natural-strategy
fills. Net PnL is computed only when every strategy fill carries broker exec_id
evidence and every exec_id has exactly one durable commission record in the same
instrument currency. Missing, duplicate, ambiguous, or cross-currency fee
evidence fails closed; fees are never guessed. This report alone never authorizes
Live Trading.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.reports.multicurrency_trade_history import (
    MulticurrencyTradeHistoryError,
    calculate_realized_trade_history,
)
from ai_asset_platform.reports.performance import (
    calculate_performance,
    calculate_performance_health,
)


STRATEGY_INTENT_PREFIX = "signal-runner:"
DEFAULT_ORDER_LOG_PATH = Path("results/paper_orders.jsonl")
DEFAULT_COMMISSION_REPORT_PATH = Path("results/ibkr_paper_commission_evidence_ledger.json")
DEFAULT_REPORT_PATH = Path("results/strategy_profitability_evidence_latest.json")
REPORT_SCHEMA_VERSION = 3


class StrategyProfitabilityEvidenceError(ValueError):
    """Raised when source evidence cannot be read without guessing."""


@dataclass(frozen=True)
class StrategyProfitabilityEvidence:
    evidence_status: str
    gross_result: str
    reason: str
    account_currency: str
    strategy_fill_count: int
    closed_trade_count: int
    excluded_ibkr_fill_count: int
    gross_performance: dict
    performance_health: dict
    realized_trades: tuple[dict, ...]
    net_performance: dict | None = None
    fees_accounted: bool = False
    fee_aware: bool = False
    net_realized_pnl: float | None = None
    net_profitability_proven: bool = False
    live_ready: bool = False


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8", errors="strict").splitlines(),
        start=1,
    ):
        text = raw.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StrategyProfitabilityEvidenceError(
                f"order log line {line_number} is malformed JSON"
            ) from exc
        if not isinstance(row, dict):
            raise StrategyProfitabilityEvidenceError(
                f"order log line {line_number} is not a JSON object"
            )
        rows.append(row)
    return rows



def _load_json_object(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except json.JSONDecodeError as exc:
        raise StrategyProfitabilityEvidenceError(
            f"{path} contains malformed JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise StrategyProfitabilityEvidenceError(
            f"{path} must contain a JSON object"
        )
    return payload


def _currency(value: object, *, field: str) -> str:
    normalized = str(value or "").strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise StrategyProfitabilityEvidenceError(
            f"{field} must be a 3-letter currency code"
        )
    return normalized


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise StrategyProfitabilityEvidenceError(f"{field} must be numeric") from exc
    if not parsed.is_finite():
        raise StrategyProfitabilityEvidenceError(f"{field} must be finite")
    return parsed


def _positive_decimal(value: object, *, field: str) -> Decimal:
    parsed = _decimal(value, field=field)
    if parsed <= 0:
        raise StrategyProfitabilityEvidenceError(f"{field} must be positive")
    return parsed


def _fill_fx_rate(record: dict, *, fill_currency: str, account_currency: str) -> Decimal:
    raw = record.get("fx_to_account_rate")
    if fill_currency == account_currency:
        if raw in (None, ""):
            return Decimal("1")
        rate = _positive_decimal(raw, field="fx_to_account_rate")
        if rate != Decimal("1"):
            raise StrategyProfitabilityEvidenceError(
                "same-currency fill requires fx_to_account_rate=1 or omission"
            )
        return rate
    if raw in (None, ""):
        raise StrategyProfitabilityEvidenceError(
            f"fee-aware fill currency {fill_currency} requires explicit "
            f"fx_to_account_rate into {account_currency}"
        )
    return _positive_decimal(raw, field="fx_to_account_rate")


def _commission_index(commission_report: dict) -> dict[str, tuple[Decimal, str]]:
    if type(commission_report.get("schema_version")) is not int or commission_report.get("schema_version") != 1:
        raise StrategyProfitabilityEvidenceError(
            "commission evidence ledger schema_version is not the current exact integer"
        )
    if commission_report.get("paper_only") is not True:
        raise StrategyProfitabilityEvidenceError(
            "commission evidence ledger is not explicitly Paper-only"
        )
    if commission_report.get("order_sent") is not False:
        raise StrategyProfitabilityEvidenceError(
            "commission evidence report unexpectedly indicates an order send"
        )
    if commission_report.get("live_order_sent") is not False:
        raise StrategyProfitabilityEvidenceError(
            "commission evidence report unexpectedly indicates a Live order send"
        )
    rows = commission_report.get("commissions")
    if not isinstance(rows, list):
        raise StrategyProfitabilityEvidenceError(
            "commission evidence report is missing commissions list"
        )

    index: dict[str, tuple[Decimal, str]] = {}
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise StrategyProfitabilityEvidenceError(
                f"commission row #{position} is not an object"
            )
        exec_id = str(row.get("exec_id", "")).strip()
        if not exec_id:
            raise StrategyProfitabilityEvidenceError(
                f"commission row #{position} is missing exec_id"
            )
        if exec_id in index:
            raise StrategyProfitabilityEvidenceError(
                f"duplicate commission evidence for exec_id={exec_id}"
            )
        commission = _decimal(
            row.get("commission"),
            field=f"commission[{exec_id}]",
        )
        currency = _currency(
            row.get("currency"),
            field=f"commission currency[{exec_id}]",
        )
        index[exec_id] = (commission, currency)
    return index


def _strategy_fill_signature(record: dict) -> tuple:
    raw_exec_ids = record.get("broker_exec_ids")
    exec_ids = tuple(str(value or "").strip() for value in raw_exec_ids) if isinstance(raw_exec_ids, list) else ()
    return (
        str(record.get("ticker", "")).strip().upper(),
        str(record.get("side", "")).strip().upper(),
        str(record.get("shares", "")),
        str(record.get("reference_price", "")),
        str(record.get("currency", "")).strip().upper(),
        str(record.get("fx_to_account_rate", "")),
        exec_ids,
    )


def _dedupe_strategy_fills_by_intent(
    strategy_fills: Iterable[dict],
) -> list[dict]:
    deduped: list[dict] = []
    seen: dict[str, tuple] = {}
    for record in strategy_fills:
        intent = str(record.get("order_intent_id", "")).strip()
        if not intent:
            raise StrategyProfitabilityEvidenceError(
                "natural strategy fill is missing order_intent_id"
            )
        signature = _strategy_fill_signature(record)
        previous = seen.get(intent)
        if previous is None:
            seen[intent] = signature
            deduped.append(record)
            continue
        if previous != signature:
            raise StrategyProfitabilityEvidenceError(
                f"conflicting duplicate natural strategy fill for order_intent_id={intent}"
            )
    return deduped


def _net_realized_trades_with_commissions(
    strategy_fills: Iterable[dict],
    *,
    commission_report: dict,
    account_currency: str,
) -> list[dict]:
    account = _currency(account_currency, field="account_currency")
    commissions = _commission_index(commission_report)
    used_exec_ids: set[str] = set()
    quantities: dict[str, int] = {}
    average_gross_cost_account: dict[str, Decimal] = {}
    average_buy_fee_account: dict[str, Decimal] = {}
    symbol_currency: dict[str, str] = {}
    net_realized: list[dict] = []

    for position, record in enumerate(strategy_fills, start=1):
        ticker = str(record.get("ticker", "")).strip().upper()
        side = str(record.get("side", "")).strip().upper()
        if not ticker or side not in {"BUY", "SELL"}:
            raise StrategyProfitabilityEvidenceError(
                f"strategy fill #{position} has invalid ticker/side"
            )
        try:
            shares = int(record.get("shares"))
        except (TypeError, ValueError) as exc:
            raise StrategyProfitabilityEvidenceError(
                f"strategy fill #{position} shares must be a whole number"
            ) from exc
        if shares <= 0:
            raise StrategyProfitabilityEvidenceError(
                f"strategy fill #{position} shares must be positive"
            )

        price = _positive_decimal(
            record.get("reference_price"),
            field=f"strategy fill #{position} reference_price",
        )
        fill_currency = _currency(
            record.get("currency"),
            field=f"strategy fill #{position} currency",
        )
        prior_currency = symbol_currency.get(ticker)
        if prior_currency is not None and prior_currency != fill_currency:
            raise StrategyProfitabilityEvidenceError(
                f"symbol {ticker} changed currency from {prior_currency} to {fill_currency}"
            )
        symbol_currency[ticker] = fill_currency
        fx_rate = _fill_fx_rate(
            record,
            fill_currency=fill_currency,
            account_currency=account,
        )

        raw_exec_ids = record.get("broker_exec_ids")
        if not isinstance(raw_exec_ids, list) or not raw_exec_ids:
            raise StrategyProfitabilityEvidenceError(
                f"strategy fill #{position} is missing broker_exec_ids"
            )
        exec_ids: list[str] = []
        for value in raw_exec_ids:
            exec_id = str(value or "").strip()
            if not exec_id:
                raise StrategyProfitabilityEvidenceError(
                    f"strategy fill #{position} contains an empty broker exec_id"
                )
            if exec_id in exec_ids:
                raise StrategyProfitabilityEvidenceError(
                    f"strategy fill #{position} contains duplicate exec_id={exec_id}"
                )
            if exec_id in used_exec_ids:
                raise StrategyProfitabilityEvidenceError(
                    f"broker exec_id={exec_id} is reused by multiple strategy fills"
                )
            exec_ids.append(exec_id)

        fee_local = Decimal("0")
        for exec_id in exec_ids:
            evidence = commissions.get(exec_id)
            if evidence is None:
                raise StrategyProfitabilityEvidenceError(
                    f"missing commission evidence for exec_id={exec_id}"
                )
            commission, commission_currency = evidence
            if commission_currency != fill_currency:
                raise StrategyProfitabilityEvidenceError(
                    f"commission currency for exec_id={exec_id} does not match "
                    f"fill currency: {commission_currency} != {fill_currency}"
                )
            fee_local += commission
            used_exec_ids.add(exec_id)

        fee_account = fee_local * fx_rate
        unit_account = price * fx_rate
        held = quantities.get(ticker, 0)

        if side == "BUY":
            prior_gross = average_gross_cost_account.get(ticker, Decimal("0"))
            prior_fee = average_buy_fee_account.get(ticker, Decimal("0"))
            new_qty = held + shares
            average_gross_cost_account[ticker] = (
                prior_gross * Decimal(held) + unit_account * Decimal(shares)
            ) / Decimal(new_qty)
            average_buy_fee_account[ticker] = (
                prior_fee * Decimal(held) + fee_account
            ) / Decimal(new_qty)
            quantities[ticker] = new_qty
            continue

        if shares > held:
            raise StrategyProfitabilityEvidenceError(
                f"confirmed SELL for {ticker} exceeds fee-aware accounted holdings"
            )
        gross_avg = average_gross_cost_account.get(ticker)
        buy_fee_avg = average_buy_fee_account.get(ticker)
        if gross_avg is None or buy_fee_avg is None:
            raise StrategyProfitabilityEvidenceError(
                f"confirmed SELL for {ticker} has no fee-aware cost basis"
            )

        gross_pnl = (unit_account - gross_avg) * Decimal(shares)
        allocated_buy_fee = buy_fee_avg * Decimal(shares)
        net_pnl = gross_pnl - allocated_buy_fee - fee_account
        if not net_pnl.is_finite():
            raise StrategyProfitabilityEvidenceError(
                f"fee-aware realized PnL for {ticker} is non-finite"
            )
        net_realized.append(
            {
                "ticker": ticker,
                "shares": shares,
                "order_intent_id": str(record.get("order_intent_id") or ""),
                "sell_exec_ids": list(exec_ids),
                "fill_currency": fill_currency,
                "account_currency": account,
                "sell_price_local": float(price),
                "sell_fx_to_account_rate": float(fx_rate),
                "gross_average_cost_account": float(gross_avg),
                "gross_realized_pnl_account": float(gross_pnl),
                "allocated_buy_commission_account": float(allocated_buy_fee),
                "sell_commission_account": float(fee_account),
                "total_commission_account": float(allocated_buy_fee + fee_account),
                "net_realized_pnl_account": float(net_pnl),
                "sold_at": (
                    str(record.get("created_at"))
                    if record.get("created_at")
                    else None
                ),
            }
        )
        remaining = held - shares
        quantities[ticker] = remaining
        if remaining == 0:
            average_gross_cost_account.pop(ticker, None)
            average_buy_fee_account.pop(ticker, None)

    return net_realized

def _is_confirmed_ibkr_fill(record: dict) -> bool:
    return (
        str(record.get("mode", "")).strip().upper() == "IBKR_PAPER"
        and str(record.get("status", "")).strip().upper() == "FILLED"
    )


def _natural_runtime_intent_matches_record(record: dict) -> bool:
    """Validate the exact durable identity shape emitted by signal_runner.

    Expected shape:
    signal-runner:<ticker>:<BUY|SELL>:<whole quantity>:<non-empty bar key>

    The bar key can itself contain colons, so only the first four separators are
    structural. Record ticker/side/quantity must agree with the identifier.
    """
    intent = str(record.get("order_intent_id", "")).strip()
    parts = intent.split(":", 4)
    if len(parts) != 5 or parts[0] != "signal-runner":
        return False

    intent_ticker = parts[1].strip().upper()
    intent_side = parts[2].strip().upper()
    quantity_text = parts[3].strip()
    bar_key = parts[4].strip()
    if not intent_ticker or intent_side not in {"BUY", "SELL"} or not bar_key:
        return False

    try:
        intent_quantity = int(quantity_text)
        record_quantity = int(record.get("shares"))
    except (TypeError, ValueError):
        return False
    if intent_quantity <= 0 or record_quantity <= 0:
        return False

    record_ticker = str(record.get("ticker", "")).strip().upper()
    record_side = str(record.get("side", "")).strip().upper()
    return (
        intent_ticker == record_ticker
        and intent_side == record_side
        and intent_quantity == record_quantity
    )


def is_natural_strategy_fill(record: dict) -> bool:
    """Return True only for confirmed fills created by the natural signal runtime."""
    return bool(
        isinstance(record, dict)
        and _is_confirmed_ibkr_fill(record)
        and _natural_runtime_intent_matches_record(record)
    )


def select_natural_strategy_fills(records: Iterable[dict]) -> list[dict]:
    return [record for record in records if is_natural_strategy_fill(record)]


def _json_safe_performance(performance) -> dict:
    payload = asdict(performance)
    factor = float(payload["profit_factor"])
    payload["profit_factor"] = factor if math.isfinite(factor) else None
    payload["profit_factor_unbounded"] = math.isinf(factor)
    return payload


def _empty_metrics() -> tuple[dict, dict]:
    performance = calculate_performance([])
    health = calculate_performance_health(performance)
    return _json_safe_performance(performance), asdict(health)


def _blocked_input_evidence(*, reason: str, account_currency: str) -> StrategyProfitabilityEvidence:
    performance, health = _empty_metrics()
    return StrategyProfitabilityEvidence(
        evidence_status="BLOCKED_INPUT_EVIDENCE",
        gross_result="UNKNOWN",
        reason=reason,
        account_currency=str(account_currency).strip().upper(),
        strategy_fill_count=0,
        closed_trade_count=0,
        excluded_ibkr_fill_count=0,
        gross_performance=performance,
        performance_health=health,
        realized_trades=(),
    )


def build_strategy_profitability_evidence(
    records: Iterable[dict],
    *,
    account_currency: str = "JPY",
    commission_report: dict | None = None,
) -> StrategyProfitabilityEvidence:
    """Build strategy evidence while excluding every non-strategy fill.

    The existing account-currency trade-history engine is reused so FX is never
    guessed. Any missing/ambiguous cost basis or FX evidence blocks the report
    instead of manufacturing a result.
    """
    rows = [record for record in records if isinstance(record, dict)]
    raw_strategy_fills = select_natural_strategy_fills(rows)
    all_ibkr_fills = [record for record in rows if _is_confirmed_ibkr_fill(record)]
    excluded = len(all_ibkr_fills) - len(raw_strategy_fills)
    account = str(account_currency).strip().upper()
    try:
        strategy_fills = _dedupe_strategy_fills_by_intent(raw_strategy_fills)
    except StrategyProfitabilityEvidenceError as exc:
        performance, health = _empty_metrics()
        return StrategyProfitabilityEvidence(
            evidence_status="BLOCKED_ACCOUNTING_EVIDENCE",
            gross_result="UNKNOWN",
            reason=f"Natural strategy accounting failed closed: {exc}",
            account_currency=account,
            strategy_fill_count=len(raw_strategy_fills),
            closed_trade_count=0,
            excluded_ibkr_fill_count=excluded,
            gross_performance=performance,
            performance_health=health,
            realized_trades=(),
        )

    if not strategy_fills:
        performance, health = _empty_metrics()
        return StrategyProfitabilityEvidence(
            evidence_status="NO_NATURAL_STRATEGY_FILLS",
            gross_result="INSUFFICIENT_EVIDENCE",
            reason=(
                "No confirmed natural strategy fills exist yet; validation/reset "
                "fills are intentionally excluded."
            ),
            account_currency=account,
            strategy_fill_count=0,
            closed_trade_count=0,
            excluded_ibkr_fill_count=excluded,
            gross_performance=performance,
            performance_health=health,
            realized_trades=(),
        )

    try:
        realized = calculate_realized_trade_history(
            strategy_fills,
            account_currency=account,
        )
    except MulticurrencyTradeHistoryError as exc:
        performance, health = _empty_metrics()
        return StrategyProfitabilityEvidence(
            evidence_status="BLOCKED_ACCOUNTING_EVIDENCE",
            gross_result="UNKNOWN",
            reason=f"Natural strategy accounting failed closed: {exc}",
            account_currency=account,
            strategy_fill_count=len(strategy_fills),
            closed_trade_count=0,
            excluded_ibkr_fill_count=excluded,
            gross_performance=performance,
            performance_health=health,
            realized_trades=(),
        )

    pnls = [float(trade.realized_pnl_account) for trade in realized]
    performance = calculate_performance(pnls)
    health = calculate_performance_health(performance)
    performance_record = _json_safe_performance(performance)
    health_record = asdict(health)

    if not realized:
        return StrategyProfitabilityEvidence(
            evidence_status="NO_NATURAL_CLOSED_TRADES",
            gross_result="INSUFFICIENT_EVIDENCE",
            reason=(
                "Natural strategy fills exist, but no natural strategy position "
                "has been closed yet."
            ),
            account_currency=account,
            strategy_fill_count=len(strategy_fills),
            closed_trade_count=0,
            excluded_ibkr_fill_count=excluded,
            gross_performance=performance_record,
            performance_health=health_record,
            realized_trades=(),
        )

    gross_result = (
        "POSITIVE_GROSS_SO_FAR"
        if performance.net_profit > 0
        else "NON_POSITIVE_GROSS_SO_FAR"
    )
    if commission_report is None:
        return StrategyProfitabilityEvidence(
            evidence_status="GROSS_RESULT_ONLY_FEES_NOT_ACCOUNTED",
            gross_result=gross_result,
            reason=(
                "Natural strategy closed trades are measurable, but durable commission/fee "
                "evidence is not available to this accounting run. "
                "Net profitability therefore remains unverified."
            ),
            account_currency=account,
            strategy_fill_count=len(strategy_fills),
            closed_trade_count=len(realized),
            excluded_ibkr_fill_count=excluded,
            gross_performance=performance_record,
            performance_health=health_record,
            realized_trades=tuple(trade.as_record() for trade in realized),
        )

    try:
        fee_aware_trades = _net_realized_trades_with_commissions(
            strategy_fills,
            commission_report=commission_report,
            account_currency=account,
        )
        net_pnls = [
            float(trade["net_realized_pnl_account"])
            for trade in fee_aware_trades
        ]
    except StrategyProfitabilityEvidenceError as exc:
        return StrategyProfitabilityEvidence(
            evidence_status="BLOCKED_FEE_EVIDENCE",
            gross_result=gross_result,
            reason=f"Fee-aware strategy accounting failed closed: {exc}",
            account_currency=account,
            strategy_fill_count=len(strategy_fills),
            closed_trade_count=len(realized),
            excluded_ibkr_fill_count=excluded,
            gross_performance=performance_record,
            performance_health=health_record,
            realized_trades=tuple(trade.as_record() for trade in realized),
        )

    if len(net_pnls) != len(realized):
        return StrategyProfitabilityEvidence(
            evidence_status="BLOCKED_FEE_EVIDENCE",
            gross_result=gross_result,
            reason=(
                "Fee-aware realized trade count does not match gross realized trade count; "
                "report blocked instead of guessing."
            ),
            account_currency=account,
            strategy_fill_count=len(strategy_fills),
            closed_trade_count=len(realized),
            excluded_ibkr_fill_count=excluded,
            gross_performance=performance_record,
            performance_health=health_record,
            realized_trades=tuple(trade.as_record() for trade in realized),
        )

    net_performance = calculate_performance(net_pnls)
    net_record = _json_safe_performance(net_performance)
    net_positive = net_performance.net_profit > 0
    return StrategyProfitabilityEvidence(
        evidence_status=(
            "NET_POSITIVE_AFTER_FEES"
            if net_positive
            else "NET_NON_POSITIVE_AFTER_FEES"
        ),
        gross_result=gross_result,
        reason=(
            "Every natural strategy fill is bound to explicit broker exec_id commission "
            "evidence; net realized PnL includes buy and sell commissions in account currency. "
            "The versioned strategy-promotion policy is not yet implemented/passed, so "
            "net_profitability_proven remains false."
        ),
        account_currency=account,
        strategy_fill_count=len(strategy_fills),
        closed_trade_count=len(realized),
        excluded_ibkr_fill_count=excluded,
        gross_performance=performance_record,
        performance_health=health_record,
        realized_trades=tuple(fee_aware_trades),
        net_performance=net_record,
        fees_accounted=True,
        fee_aware=True,
        net_realized_pnl=float(net_performance.net_profit),
        net_profitability_proven=False,
        live_ready=False,
    )


def evidence_record(result: StrategyProfitabilityEvidence) -> dict:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        **asdict(result),
        "strategy_intent_prefix": STRATEGY_INTENT_PREFIX,
        "strategy_intent_shape": "signal-runner:<ticker>:<BUY|SELL>:<quantity>:<bar-key>",
        "paper_only": True,
        "broker_connection_used": False,
        "order_sent": False,
        "live_trading": "PROHIBITED",
    }


def audit_strategy_profitability_evidence(
    *,
    order_log_path: Path = DEFAULT_ORDER_LOG_PATH,
    commission_report_path: Path = DEFAULT_COMMISSION_REPORT_PATH,
    account_currency: str | None = None,
) -> StrategyProfitabilityEvidence:
    account = str(account_currency or SETTINGS.account_currency)
    try:
        records = _load_jsonl(order_log_path)
        commission_report = _load_json_object(commission_report_path)
    except (StrategyProfitabilityEvidenceError, UnicodeError, OSError) as exc:
        return _blocked_input_evidence(
            reason=f"Profitability source evidence is unreadable; report blocked: {exc}",
            account_currency=account,
        )
    return build_strategy_profitability_evidence(
        records,
        account_currency=account,
        commission_report=commission_report,
    )


def persist_strategy_profitability_evidence(
    result: StrategyProfitabilityEvidence,
    *,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(evidence_record(result), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def main() -> int:
    result = audit_strategy_profitability_evidence()
    persist_strategy_profitability_evidence(result)
    print("===== NATURAL STRATEGY PROFITABILITY EVIDENCE =====")
    print("EVIDENCE STATUS       :", result.evidence_status)
    print("GROSS RESULT          :", result.gross_result)
    print("ACCOUNT CURRENCY      :", result.account_currency)
    print("STRATEGY FILLS        :", result.strategy_fill_count)
    print("CLOSED TRADES         :", result.closed_trade_count)
    print("EXCLUDED IBKR FILLS   :", result.excluded_ibkr_fill_count)
    print("GROSS NET PNL         :", result.gross_performance["net_profit"])
    print("WIN RATE              :", result.gross_performance["win_rate"])
    print("PROFIT FACTOR         :", result.gross_performance["profit_factor"])
    print("MAX DRAWDOWN          :", result.gross_performance["maximum_drawdown"])
    print("FEES ACCOUNTED        :", result.fees_accounted)
    print("FEE AWARE             :", result.fee_aware)
    print("NET REALIZED PNL      :", result.net_realized_pnl)
    print("NET PROFIT PROVEN     :", result.net_profitability_proven)
    print("NET PERFORMANCE       :", result.net_performance)
    print("LIVE READY            :", result.live_ready)
    print("REASON                :", result.reason)
    print("REPORT                :", DEFAULT_REPORT_PATH)
    print("BROKER CONNECTION USED: False")
    print("ORDER SENT            : False")
    print("LIVE TRADING          : PROHIBITED")
    return 1 if result.evidence_status.startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
