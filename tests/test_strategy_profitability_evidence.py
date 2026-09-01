from __future__ import annotations

from pathlib import Path

from ai_asset_platform.reports.strategy_profitability_evidence import (
    STRATEGY_INTENT_PREFIX,
    build_strategy_profitability_evidence,
    evidence_record,
    is_natural_strategy_fill,
)


def _fill(
    *,
    intent: str,
    side: str,
    price: float,
    ticker: str = "9432.T",
    shares: int = 100,
    currency: str = "JPY",
    fx: float | None = 1.0,
) -> dict:
    row = {
        "created_at": "2026-09-01T10:00:00+09:00",
        "mode": "IBKR_PAPER",
        "ticker": ticker,
        "side": side,
        "shares": shares,
        "reference_price": price,
        "currency": currency,
        "status": "FILLED",
        "order_intent_id": intent,
    }
    if fx is not None:
        row["fx_to_account_rate"] = fx
    return row


def test_natural_strategy_filter_requires_exact_runtime_prefix():
    natural = _fill(
        intent=f"{STRATEGY_INTENT_PREFIX}9432.T:BUY:100:2026-09-01",
        side="BUY",
        price=150.0,
    )
    validation = _fill(
        intent="broker-recovery:controlled-proof",
        side="BUY",
        price=150.0,
    )
    legacy = dict(natural, mode="PAPER")

    assert is_natural_strategy_fill(natural) is True
    assert is_natural_strategy_fill(validation) is False
    assert is_natural_strategy_fill(legacy) is False


def test_metrics_use_only_natural_strategy_closed_trades():
    records = [
        _fill(intent="controlled-proof:buy", side="BUY", price=100.0),
        _fill(intent="controlled-proof:sell", side="SELL", price=300.0),
        _fill(
            intent=f"{STRATEGY_INTENT_PREFIX}9432.T:BUY:100:2026-09-01",
            side="BUY",
            price=150.0,
        ),
        _fill(
            intent=f"{STRATEGY_INTENT_PREFIX}9432.T:SELL:100:2026-09-02",
            side="SELL",
            price=160.0,
        ),
    ]

    result = build_strategy_profitability_evidence(records, account_currency="JPY")

    assert result.strategy_fill_count == 2
    assert result.closed_trade_count == 1
    assert result.excluded_ibkr_fill_count == 2
    assert result.gross_performance["net_profit"] == 1000.0
    assert result.gross_performance["win_rate"] == 100.0
    assert result.gross_result == "POSITIVE_GROSS_SO_FAR"
    assert result.evidence_status == "GROSS_RESULT_ONLY_FEES_NOT_ACCOUNTED"
    assert result.fees_accounted is False
    assert result.net_profitability_proven is False
    assert result.live_ready is False


def test_no_natural_strategy_fill_never_reuses_validation_profit():
    records = [
        _fill(intent="controlled-proof:buy", side="BUY", price=100.0),
        _fill(intent="controlled-proof:sell", side="SELL", price=300.0),
    ]

    result = build_strategy_profitability_evidence(records, account_currency="JPY")

    assert result.evidence_status == "NO_NATURAL_STRATEGY_FILLS"
    assert result.gross_result == "INSUFFICIENT_EVIDENCE"
    assert result.strategy_fill_count == 0
    assert result.closed_trade_count == 0
    assert result.excluded_ibkr_fill_count == 2
    assert result.gross_performance["net_profit"] == 0.0


def test_open_natural_position_is_not_counted_as_profit():
    records = [
        _fill(
            intent=f"{STRATEGY_INTENT_PREFIX}9432.T:BUY:100:2026-09-01",
            side="BUY",
            price=150.0,
        )
    ]

    result = build_strategy_profitability_evidence(records, account_currency="JPY")

    assert result.evidence_status == "NO_NATURAL_CLOSED_TRADES"
    assert result.closed_trade_count == 0
    assert result.gross_performance["net_profit"] == 0.0


def test_missing_strategy_cost_basis_fails_closed():
    records = [
        _fill(
            intent=f"{STRATEGY_INTENT_PREFIX}9432.T:SELL:100:2026-09-01",
            side="SELL",
            price=160.0,
        )
    ]

    result = build_strategy_profitability_evidence(records, account_currency="JPY")

    assert result.evidence_status == "BLOCKED_ACCOUNTING_EVIDENCE"
    assert result.gross_result == "UNKNOWN"
    assert result.net_profitability_proven is False
    assert result.live_ready is False


def test_cross_currency_fx_is_required_instead_of_guessed():
    records = [
        _fill(
            intent=f"{STRATEGY_INTENT_PREFIX}AAPL:BUY:1:2026-09-01",
            side="BUY",
            price=100.0,
            ticker="AAPL",
            shares=1,
            currency="USD",
            fx=None,
        )
    ]

    result = build_strategy_profitability_evidence(records, account_currency="JPY")

    assert result.evidence_status == "BLOCKED_ACCOUNTING_EVIDENCE"
    assert "FX" in result.reason or "fx" in result.reason


def test_serialized_evidence_explicitly_prohibits_live_and_orders():
    result = build_strategy_profitability_evidence([], account_currency="JPY")
    record = evidence_record(result)

    assert record["paper_only"] is True
    assert record["broker_connection_used"] is False
    assert record["order_sent"] is False
    assert record["live_trading"] == "PROHIBITED"
    assert record["live_ready"] is False
    assert record["net_profitability_proven"] is False


def test_module_contains_no_broker_mutation_api_calls():
    source_path = Path(__file__).parents[1] / "src" / "ai_asset_platform" / "reports" / "strategy_profitability_evidence.py"
    source = source_path.read_text(encoding="utf-8")

    for forbidden in (
        "placeOrder(",
        "cancelOrder(",
        "reqOpenOrders(",
        "reqAllOpenOrders(",
        "enable_live_trading=True",
        "live_trading_unlocked=True",
    ):
        assert forbidden not in source
