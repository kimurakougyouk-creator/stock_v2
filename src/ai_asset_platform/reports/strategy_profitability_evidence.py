"""Read-only profitability evidence for natural verified IBKR Paper strategy fills.

Only fills whose durable ``order_intent_id`` starts with the exact
``signal-runner:paper-pilot:`` prefix are treated as strategy evidence. This
keeps capability proofs, resets, recovery fills, derivatives, and legacy local
Paper simulations out of strategy-performance metrics.

This module never connects to a broker and never creates, changes, cancels, or
transmits an order. Reported PnL is explicitly gross of commissions/fees because
the current durable fill schema does not persist commission evidence. Therefore
this report must never claim that net profitability is proven or that Live
Trading is ready.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
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


STRATEGY_INTENT_PREFIX = "signal-runner:paper-pilot:"
DEFAULT_ORDER_LOG_PATH = Path("results/paper_orders.jsonl")
DEFAULT_REPORT_PATH = Path("results/strategy_profitability_evidence_latest.json")
REPORT_SCHEMA_VERSION = 1


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
    fees_accounted: bool = False
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


def _is_confirmed_ibkr_fill(record: dict) -> bool:
    return (
        str(record.get("mode", "")).strip().upper() == "IBKR_PAPER"
        and str(record.get("status", "")).strip().upper() == "FILLED"
    )


def is_natural_strategy_fill(record: dict) -> bool:
    """Return True only for confirmed fills created by the natural signal runtime."""
    if not isinstance(record, dict) or not _is_confirmed_ibkr_fill(record):
        return False
    intent = str(record.get("order_intent_id", "")).strip()
    return intent.startswith(STRATEGY_INTENT_PREFIX)


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
) -> StrategyProfitabilityEvidence:
    """Build gross strategy evidence while excluding every non-strategy fill.

    The existing account-currency trade-history engine is reused so FX is never
    guessed. Any missing/ambiguous cost basis or FX evidence blocks the report
    instead of manufacturing a result.
    """
    rows = [record for record in records if isinstance(record, dict)]
    strategy_fills = select_natural_strategy_fills(rows)
    all_ibkr_fills = [record for record in rows if _is_confirmed_ibkr_fill(record)]
    excluded = len(all_ibkr_fills) - len(strategy_fills)
    account = str(account_currency).strip().upper()

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
    return StrategyProfitabilityEvidence(
        evidence_status="GROSS_RESULT_ONLY_FEES_NOT_ACCOUNTED",
        gross_result=gross_result,
        reason=(
            "Natural strategy closed trades are measurable, but durable commission/fee "
            "evidence is not yet included in this accounting path. Net profitability "
            "therefore remains unverified."
        ),
        account_currency=account,
        strategy_fill_count=len(strategy_fills),
        closed_trade_count=len(realized),
        excluded_ibkr_fill_count=excluded,
        gross_performance=performance_record,
        performance_health=health_record,
        realized_trades=tuple(trade.as_record() for trade in realized),
    )


def evidence_record(result: StrategyProfitabilityEvidence) -> dict:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        **asdict(result),
        "strategy_intent_prefix": STRATEGY_INTENT_PREFIX,
        "paper_only": True,
        "broker_connection_used": False,
        "order_sent": False,
        "live_trading": "PROHIBITED",
    }


def audit_strategy_profitability_evidence(
    *,
    order_log_path: Path = DEFAULT_ORDER_LOG_PATH,
    account_currency: str | None = None,
) -> StrategyProfitabilityEvidence:
    account = str(account_currency or SETTINGS.account_currency)
    try:
        records = _load_jsonl(order_log_path)
    except (StrategyProfitabilityEvidenceError, UnicodeError, OSError) as exc:
        return _blocked_input_evidence(
            reason=f"Profitability source evidence is unreadable; report blocked: {exc}",
            account_currency=account,
        )
    return build_strategy_profitability_evidence(
        records,
        account_currency=account,
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
    print("NET PROFIT PROVEN     :", result.net_profitability_proven)
    print("LIVE READY            :", result.live_ready)
    print("REASON                :", result.reason)
    print("REPORT                :", DEFAULT_REPORT_PATH)
    print("BROKER CONNECTION USED: False")
    print("ORDER SENT            : False")
    print("LIVE TRADING          : PROHIBITED")
    return 1 if result.evidence_status.startswith("BLOCKED_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
