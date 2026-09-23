from __future__ import annotations

from datetime import datetime, timezone
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
    exec_ids: list[str] | None = None,
    strategy_source_sha: str | None = "c" * 40,
    strategy_parameters_sha: str | None = "e" * 64,
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
    if strategy_source_sha is not None:
        row["strategy_source_sha"] = strategy_source_sha
    if strategy_parameters_sha is not None:
        row["strategy_parameters_sha"] = strategy_parameters_sha
    if fx is not None:
        row["fx_to_account_rate"] = fx
    if exec_ids is not None:
        row["broker_exec_ids"] = exec_ids
        if exec_ids:
            per_exec = shares / len(exec_ids)
            row["broker_exec_fills"] = [
                {"exec_id": exec_id, "shares": per_exec}
                for exec_id in exec_ids
            ]
    return row


def _natural_intent(
    *, ticker: str, side: str, shares: int, bar_key: str = "2026-09-01T10:00:00+09:00"
) -> str:
    return f"{STRATEGY_INTENT_PREFIX}{ticker}:{side}:{shares}:{bar_key}"


def _commission_report(*rows: dict) -> dict:
    return {
        "schema_version": 1,
        "paper_only": True,
        "order_sent": False,
        "live_order_sent": False,
        "commissions": list(rows),
    }


def _commission(exec_id: str, commission: float, currency: str) -> dict:
    return {
        "exec_id": exec_id,
        "commission": commission,
        "currency": currency,
        "realized_pnl": None,
    }


def test_natural_strategy_filter_matches_actual_signal_runner_intent_shape():
    natural = _fill(
        intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
        side="BUY",
        price=150.0,
    )
    validation = _fill(
        intent="signal-runner:paper-pilot:9432.T:BUY:100:2026-09-01",
        side="BUY",
        price=150.0,
    )
    recovery = _fill(
        intent="broker-recovery:controlled-proof",
        side="BUY",
        price=150.0,
    )
    legacy = dict(natural, mode="PAPER")

    assert is_natural_strategy_fill(natural) is True
    assert is_natural_strategy_fill(validation) is False
    assert is_natural_strategy_fill(recovery) is False
    assert is_natural_strategy_fill(legacy) is False


def test_natural_strategy_filter_requires_record_identity_to_match_intent():
    intent = _natural_intent(ticker="9432.T", side="BUY", shares=100)
    assert is_natural_strategy_fill(_fill(intent=intent, side="SELL", price=150.0)) is False
    assert is_natural_strategy_fill(
        _fill(intent=intent, side="BUY", price=150.0, ticker="AAPL", shares=100)
    ) is False
    assert is_natural_strategy_fill(
        _fill(intent=intent, side="BUY", price=150.0, shares=99)
    ) is False


def test_metrics_use_only_natural_strategy_closed_trades():
    records = [
        _fill(intent="controlled-proof:buy", side="BUY", price=100.0),
        _fill(intent="controlled-proof:sell", side="SELL", price=300.0),
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
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
    assert result.fee_aware is False
    assert result.net_realized_pnl is None
    assert result.net_profitability_proven is False
    assert result.live_ready is False
    assert result.broker_provenance_verified is False


def test_no_natural_strategy_fill_never_reuses_validation_profit():
    records = [
        _fill(intent="controlled-proof:buy", side="BUY", price=100.0),
        _fill(intent="controlled-proof:sell", side="SELL", price=300.0),
        _fill(
            intent="signal-runner:paper-pilot:9432.T:BUY:100:2026-09-01",
            side="BUY",
            price=100.0,
        ),
        _fill(
            intent="signal-runner:paper-pilot:9432.T:SELL:100:2026-09-02",
            side="SELL",
            price=300.0,
        ),
    ]

    result = build_strategy_profitability_evidence(records, account_currency="JPY")

    assert result.evidence_status == "NO_NATURAL_STRATEGY_FILLS"
    assert result.gross_result == "INSUFFICIENT_EVIDENCE"
    assert result.strategy_fill_count == 0
    assert result.closed_trade_count == 0
    assert result.excluded_ibkr_fill_count == 4
    assert result.gross_performance["net_profit"] == 0.0


def test_open_natural_position_is_not_counted_as_profit():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
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
            intent=_natural_intent(ticker="9432.T", side="SELL", shares=100),
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
            intent=_natural_intent(ticker="AAPL", side="BUY", shares=1),
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


def test_serialized_evidence_matches_live_cash_readiness_schema_and_blocks_live():
    result = build_strategy_profitability_evidence([], account_currency="JPY")
    record = evidence_record(
        result,
        source_sha="a" * 40,
        generated_at=datetime(2026, 9, 23, 3, 0, tzinfo=timezone.utc),
    )

    assert record["schema_version"] == 4
    assert record["source_sha"] == "a" * 40
    assert record["generated_at"] == "2026-09-23T03:00:00+00:00"
    assert record["paper_only"] is True
    assert record["broker_connection_used"] is False
    assert record["order_sent"] is False
    assert record["live_trading"] == "PROHIBITED"
    assert record["live_ready"] is False
    assert record["fee_aware"] is False
    assert record["net_realized_pnl"] is None
    assert record["net_profitability_proven"] is False
    assert record["strategy_intent_shape"] == (
        "signal-runner:<ticker>:<BUY|SELL>:<quantity>:<bar-key>"
    )


def test_fee_aware_jpy_roundtrip_reports_true_net_pnl():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]
    commissions = _commission_report(
        _commission("buy-1", 5.0, "JPY"),
        _commission("sell-1", 5.0, "JPY"),
    )

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=commissions,
    )

    assert result.gross_performance["net_profit"] == 1000.0
    assert result.net_realized_pnl == 990.0
    assert result.net_performance is not None
    assert result.net_performance["net_profit"] == 990.0
    assert result.evidence_status == "NET_POSITIVE_AFTER_FEES"
    assert result.fees_accounted is True
    assert result.fee_aware is True
    assert result.net_profitability_proven is False
    assert result.live_ready is False


def test_fee_aware_evidence_counts_unattributed_broker_recovery_fills():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
        _fill(
            intent="broker-recovery:lost-natural-exec",
            side="SELL",
            price=120.0,
            exec_ids=["recovered-1"],
        ),
    ]
    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-1", 5.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )

    assert result.unattributed_recovery_fill_count == 1


def test_fee_aware_cross_currency_uses_fill_fx_for_commissions():
    records = [
        _fill(
            intent=_natural_intent(ticker="AAPL", side="BUY", shares=1),
            side="BUY",
            price=100.0,
            ticker="AAPL",
            shares=1,
            currency="USD",
            fx=150.0,
            exec_ids=["buy-usd"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="AAPL",
                side="SELL",
                shares=1,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=110.0,
            ticker="AAPL",
            shares=1,
            currency="USD",
            fx=150.0,
            exec_ids=["sell-usd"],
        ),
    ]
    commissions = _commission_report(
        _commission("buy-usd", 1.0, "USD"),
        _commission("sell-usd", 1.0, "USD"),
    )

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=commissions,
    )

    assert result.gross_performance["net_profit"] == 1500.0
    assert result.net_realized_pnl == 1200.0
    assert result.fees_accounted is True
    assert result.net_profitability_proven is False


def test_missing_commission_evidence_fails_closed():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]
    commissions = _commission_report(_commission("buy-1", 5.0, "JPY"))

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=commissions,
    )

    assert result.evidence_status == "BLOCKED_FEE_EVIDENCE"
    assert result.fees_accounted is False
    assert result.net_realized_pnl is None
    assert result.net_profitability_proven is False
    assert "sell-1" in result.reason


def test_missing_exec_id_binding_fails_closed():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=None,
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(_commission("sell-1", 5.0, "JPY")),
    )

    assert result.evidence_status == "BLOCKED_FEE_EVIDENCE"
    assert "broker_exec_ids" in result.reason
    assert result.fees_accounted is False


def test_reused_exec_id_across_strategy_fills_fails_closed():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["same"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["same"],
        ),
    ]

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(_commission("same", 5.0, "JPY")),
    )

    assert result.evidence_status == "BLOCKED_FEE_EVIDENCE"
    assert "reused" in result.reason
    assert result.fees_accounted is False


def test_commission_currency_mismatch_fails_closed():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]
    commissions = _commission_report(
        _commission("buy-1", 5.0, "USD"),
        _commission("sell-1", 5.0, "JPY"),
    )

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=commissions,
    )

    assert result.evidence_status == "BLOCKED_FEE_EVIDENCE"
    assert "currency" in result.reason
    assert result.fees_accounted is False


def test_complete_fee_evidence_can_prove_non_positive_net_result_without_live_ready():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=150.0,
            exec_ids=["sell-1"],
        ),
    ]
    commissions = _commission_report(
        _commission("buy-1", 5.0, "JPY"),
        _commission("sell-1", 5.0, "JPY"),
    )

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=commissions,
    )

    assert result.net_realized_pnl == -10.0
    assert result.evidence_status == "NET_NON_POSITIVE_AFTER_FEES"
    assert result.fees_accounted is True
    assert result.net_profitability_proven is False
    assert result.live_ready is False


def test_conflicting_duplicate_intent_fails_closed_before_gross_or_net_diverge():
    intent = _natural_intent(ticker="9432.T", side="BUY", shares=100)
    records = [
        _fill(
            intent=intent,
            side="BUY",
            price=200.0,
            exec_ids=["buy-a"],
        ),
        _fill(
            intent=intent,
            side="BUY",
            price=100.0,
            exec_ids=["buy-b"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-a", 5.0, "JPY"),
            _commission("buy-b", 5.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )

    assert result.evidence_status == "BLOCKED_ACCOUNTING_EVIDENCE"
    assert "conflicting duplicate" in result.reason
    assert result.net_profitability_proven is False


def test_exact_duplicate_intent_is_idempotent_for_gross_and_net():
    buy = _fill(
        intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
        side="BUY",
        price=150.0,
        exec_ids=["buy-1"],
    )
    records = [
        buy,
        dict(buy),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-1", 5.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )

    assert result.gross_performance["net_profit"] == 1000.0
    assert result.net_realized_pnl == 990.0
    assert result.closed_trade_count == 1
    assert result.net_profitability_proven is False


def test_fee_aware_realized_trade_serializes_commission_allocation():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-1", 5.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )

    assert len(result.realized_trades) == 1
    trade = result.realized_trades[0]
    assert trade["gross_realized_pnl_account"] == 1000.0
    assert trade["allocated_buy_commission_account"] == 5.0
    assert trade["sell_commission_account"] == 5.0
    assert trade["total_commission_account"] == 10.0
    assert trade["net_realized_pnl_account"] == 990.0
    assert trade["sell_exec_ids"] == ["sell-1"]
    assert len(trade["buy_contributions_weighted_average"]) == 1
    assert trade["buy_contributions_weighted_average"][0]["buy_exec_ids"] == ["buy-1"]


def test_partial_close_retains_all_weighted_average_buy_exec_provenance():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=100.0,
            shares=100,
            exec_ids=["buy-a"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="BUY",
                shares=100,
                bar_key="2026-09-01T11:00:00+09:00",
            ),
            side="BUY",
            price=200.0,
            shares=100,
            exec_ids=["buy-b"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=180.0,
            shares=100,
            exec_ids=["sell-1"],
        ),
    ]
    commissions = _commission_report(
        _commission("buy-a", 10.0, "JPY"),
        _commission("buy-b", 20.0, "JPY"),
        _commission("sell-1", 5.0, "JPY"),
    )

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=commissions,
    )

    trade = result.realized_trades[0]
    contributions = trade["buy_contributions_weighted_average"]
    assert [c["buy_exec_ids"] for c in contributions] == [["buy-a"], ["buy-b"]]
    assert [c["allocated_shares_weighted_average"] for c in contributions] == [50.0, 50.0]
    assert [c["allocated_commission_account"] for c in contributions] == [5.0, 10.0]
    assert trade["allocated_buy_commission_account"] == 15.0
    assert trade["sell_commission_account"] == 5.0
    assert trade["gross_realized_pnl_account"] == 3000.0
    assert trade["net_realized_pnl_account"] == 2980.0
    assert result.net_realized_pnl == 2980.0
    assert result.net_profitability_proven is False


def test_incomplete_execution_quantity_coverage_fails_closed():
    buy = _fill(
        intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
        side="BUY",
        price=150.0,
        exec_ids=["buy-a", "buy-b"],
    )
    buy["broker_exec_fills"] = [{"exec_id": "buy-a", "shares": 40}]
    records = [
        buy,
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]

    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-a", 2.0, "JPY"),
            _commission("buy-b", 3.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )

    assert result.evidence_status == "BLOCKED_FEE_EVIDENCE"
    assert "execution quantity" in result.reason
    assert result.fees_accounted is False
    assert result.net_realized_pnl is None


def test_execution_quantity_ids_must_match_commission_bound_exec_ids():
    buy = _fill(
        intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
        side="BUY",
        price=150.0,
        exec_ids=["buy-a"],
    )
    buy["broker_exec_fills"] = [{"exec_id": "different", "shares": 100}]
    result = build_strategy_profitability_evidence(
        [
            buy,
            _fill(
                intent=_natural_intent(
                    ticker="9432.T",
                    side="SELL",
                    shares=100,
                    bar_key="2026-09-02T10:00:00+09:00",
                ),
                side="SELL",
                price=160.0,
                exec_ids=["sell-1"],
            ),
        ],
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-a", 5.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )

    assert result.evidence_status == "BLOCKED_FEE_EVIDENCE"
    assert "do not match broker_exec_ids" in result.reason


def test_fee_aware_report_carries_one_exact_strategy_source_sha():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]
    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-1", 5.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )
    assert result.strategy_source_sha == "c" * 40




def test_fee_aware_local_ledgers_never_claim_authenticated_broker_provenance():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
        ),
    ]
    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-1", 5.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )

    assert result.fees_accounted is True
    assert result.broker_provenance_verified is False
    assert "not yet authenticated" in result.reason




def test_mixed_strategy_parameter_sha_never_proves_one_strategy():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
            strategy_parameters_sha="e" * 64,
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
            strategy_parameters_sha="f" * 64,
        ),
    ]
    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-1", 5.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )
    assert result.strategy_parameters_sha is None
    assert result.net_profitability_proven is False
    assert result.live_ready is False


def test_mixed_strategy_source_sha_never_proves_one_version():
    records = [
        _fill(
            intent=_natural_intent(ticker="9432.T", side="BUY", shares=100),
            side="BUY",
            price=150.0,
            exec_ids=["buy-1"],
            strategy_source_sha="c" * 40,
        ),
        _fill(
            intent=_natural_intent(
                ticker="9432.T",
                side="SELL",
                shares=100,
                bar_key="2026-09-02T10:00:00+09:00",
            ),
            side="SELL",
            price=160.0,
            exec_ids=["sell-1"],
            strategy_source_sha="d" * 40,
        ),
    ]
    result = build_strategy_profitability_evidence(
        records,
        account_currency="JPY",
        commission_report=_commission_report(
            _commission("buy-1", 5.0, "JPY"),
            _commission("sell-1", 5.0, "JPY"),
        ),
    )
    assert result.strategy_source_sha is None
    assert result.net_profitability_proven is False
    assert result.live_ready is False


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