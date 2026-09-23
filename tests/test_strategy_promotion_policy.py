from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from ai_asset_platform.reports.strategy_promotion_policy import (
    StrategyPromotionPolicy,
    evaluate_strategy_promotion,
    load_strategy_promotion_policy,
    persist_blocked_strategy_promotion_failure,
)


SOURCE_SHA = "a" * 40
STRATEGY_SHA = "c" * 40
NOW = datetime(2026, 9, 23, 3, 0, tzinfo=timezone.utc)


def _policy(**overrides) -> StrategyPromotionPolicy:
    values = dict(
        schema_version=1,
        policy_version="test-v1",
        enabled=True,
        strategy_source_sha=STRATEGY_SHA,
        minimum_closed_trades=3,
        minimum_net_profit_account_currency=100.0,
        maximum_drawdown_account_currency=500.0,
        minimum_win_rate=50.0,
        minimum_profit_factor=1.2,
        minimum_observation_span_seconds=2 * 24 * 60 * 60,
        maximum_evidence_age_seconds=7 * 24 * 60 * 60,
    )
    values.update(overrides)
    return StrategyPromotionPolicy(**values)


def _trade(day: int, *, pnl: float) -> dict:
    sold = f"2026-09-{20 + day:02d}T03:00:00+00:00"
    bought = f"2026-09-{19 + day:02d}T03:00:00+00:00"
    return {
        "ticker": "9432.T",
        "shares": 100,
        "order_intent_id": f"signal-runner:9432.T:SELL:100:bar-{day}",
        "sell_exec_ids": [f"sell-{day}"],
        "buy_contributions_weighted_average": [
            {
                "order_intent_id": f"signal-runner:9432.T:BUY:100:buy-{day}",
                "buy_exec_ids": [f"buy-{day}"],
                "created_at": bought,
            }
        ],
        "net_realized_pnl_account": pnl,
        "sold_at": sold,
    }


def _report() -> dict:
    trades = [_trade(0, pnl=150.0), _trade(1, pnl=-50.0), _trade(2, pnl=200.0)]
    return {
        "schema_version": 4,
        "evidence_status": "NET_POSITIVE_AFTER_FEES",
        "source_sha": SOURCE_SHA,
        "strategy_source_sha": STRATEGY_SHA,
        "generated_at": "2026-09-23T02:30:00+00:00",
        "paper_only": True,
        "broker_connection_used": False,
        "order_sent": False,
        "live_trading": "PROHIBITED",
        "fees_accounted": True,
        "fee_aware": True,
        "closed_trade_count": 3,
        "net_realized_pnl": 300.0,
        "net_performance": {
            "total_trades": 3,
            "win_rate": 66.6666666667,
            "net_profit": 300.0,
            "profit_factor": 7.0,
            "profit_factor_unbounded": False,
            "maximum_drawdown": 50.0,
        },
        "realized_trades": trades,
    }


def test_disabled_checked_in_policy_fails_closed_without_thresholds(tmp_path: Path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy_version": "draft",
                "enabled": False,
                "minimum_closed_trades": None,
            }
        ),
        encoding="utf-8",
    )
    policy = load_strategy_promotion_policy(path)
    decision = evaluate_strategy_promotion(
        _report(),
        policy,
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.status == "PROMOTION_POLICY_BLOCKED"
    assert decision.promotion_policy_passed is False
    assert decision.normal_live_strategy_deployment_allowed is False
    assert "disabled" in " ".join(decision.blockers)


def test_complete_enabled_policy_can_pass_but_never_authorizes_live():
    decision = evaluate_strategy_promotion(
        _report(),
        _policy(),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.status == "PROMOTION_POLICY_PASS"
    assert decision.promotion_policy_passed is True
    assert decision.normal_live_strategy_deployment_allowed is False
    assert decision.blockers == ()


def test_missing_fee_accounting_blocks():
    report = _report()
    report["fees_accounted"] = False

    decision = evaluate_strategy_promotion(
        report,
        _policy(),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("fees_accounted" in blocker for blocker in decision.blockers)


def test_minimum_closed_trades_blocks():
    report = _report()
    report["closed_trade_count"] = 2
    report["realized_trades"] = report["realized_trades"][:2]
    report["net_realized_pnl"] = 100.0
    report["net_performance"].update(
        total_trades=2,
        win_rate=50.0,
        net_profit=100.0,
        profit_factor=3.0,
        profit_factor_unbounded=False,
        maximum_drawdown=50.0,
    )

    decision = evaluate_strategy_promotion(
        report,
        _policy(),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("closed trades" in blocker for blocker in decision.blockers)


def test_maximum_drawdown_blocks():
    report = _report()

    decision = evaluate_strategy_promotion(
        report,
        _policy(maximum_drawdown_account_currency=49.0),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("maximum drawdown" in blocker for blocker in decision.blockers)


def test_stale_latest_trade_blocks():
    decision = evaluate_strategy_promotion(
        _report(),
        _policy(maximum_evidence_age_seconds=60),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("evidence age" in blocker for blocker in decision.blockers)


def test_minimum_observation_span_blocks():
    decision = evaluate_strategy_promotion(
        _report(),
        _policy(minimum_observation_span_seconds=10 * 24 * 60 * 60),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("observation span" in blocker for blocker in decision.blockers)


def test_invalid_source_sha_blocks_even_when_metrics_pass():
    decision = evaluate_strategy_promotion(
        _report(),
        _policy(),
        source_sha="not-a-sha",
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("source_sha" in blocker for blocker in decision.blockers)


def test_profitability_evidence_must_be_bound_to_same_source_sha():
    report = _report()
    report["source_sha"] = "b" * 40

    decision = evaluate_strategy_promotion(
        report,
        _policy(),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("does not match" in blocker for blocker in decision.blockers)


def test_strategy_fill_source_must_match_policy_target():
    report = _report()
    report["strategy_source_sha"] = "d" * 40

    decision = evaluate_strategy_promotion(
        report,
        _policy(),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("policy target" in blocker for blocker in decision.blockers)


def test_missing_strategy_source_evidence_blocks():
    report = _report()
    report["strategy_source_sha"] = None

    decision = evaluate_strategy_promotion(
        report,
        _policy(),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("strategy_source_sha" in blocker for blocker in decision.blockers)


def test_inconsistent_summary_metrics_fail_closed():
    report = _report()
    report["net_realized_pnl"] = 999999.0
    report["net_performance"]["net_profit"] = 999999.0

    decision = evaluate_strategy_promotion(
        report,
        _policy(),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is False
    assert any("inconsistent" in blocker for blocker in decision.blockers)


def test_blocked_failure_overwrites_stale_pass_artifact(tmp_path: Path):
    path = tmp_path / "decision.json"
    path.write_text(
        json.dumps(
            {
                "status": "PROMOTION_POLICY_PASS",
                "promotion_policy_passed": True,
                "normal_live_strategy_deployment_allowed": False,
            }
        ),
        encoding="utf-8",
    )

    persist_blocked_strategy_promotion_failure(
        "current input unreadable",
        report_path=path,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "PROMOTION_POLICY_BLOCKED"
    assert payload["promotion_policy_passed"] is False
    assert payload["normal_live_strategy_deployment_allowed"] is False
    assert payload["live_trading"] == "PROHIBITED"
    assert "current input unreadable" in payload["blockers"]


def test_unbounded_profit_factor_can_satisfy_minimum():
    report = _report()
    report["realized_trades"][0]["net_realized_pnl_account"] = 100.0
    report["realized_trades"][1]["net_realized_pnl_account"] = 200.0
    report["realized_trades"][2]["net_realized_pnl_account"] = 300.0
    report["net_realized_pnl"] = 600.0
    report["net_performance"].update(
        total_trades=3,
        win_rate=100.0,
        net_profit=600.0,
        profit_factor=None,
        profit_factor_unbounded=True,
        maximum_drawdown=0.0,
    )

    decision = evaluate_strategy_promotion(
        report,
        _policy(minimum_profit_factor=99.0),
        source_sha=SOURCE_SHA,
        now=NOW,
    )

    assert decision.promotion_policy_passed is True
    assert decision.observed_profit_factor is None


def test_enabled_policy_requires_all_mandatory_numeric_thresholds(tmp_path: Path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy_version": "broken",
                "enabled": True,
                "strategy_source_sha": STRATEGY_SHA,
                "minimum_closed_trades": None,
            }
        ),
        encoding="utf-8",
    )

    try:
        load_strategy_promotion_policy(path)
    except ValueError as exc:
        assert "minimum_closed_trades" in str(exc)
    else:
        raise AssertionError("enabled policy must fail closed when thresholds are missing")


def test_module_contains_no_broker_mutation_api_calls():
    source_path = (
        Path(__file__).parents[1]
        / "src"
        / "ai_asset_platform"
        / "reports"
        / "strategy_promotion_policy.py"
    )
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