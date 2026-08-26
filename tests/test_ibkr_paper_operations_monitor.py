from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import ai_asset_platform.brokers.ibkr_paper_operations_monitor as module
from ai_asset_platform.brokers.ibkr_all_open_orders_snapshot import (
    IbkrAllOpenOrdersSnapshot,
    IbkrOpenOrderEvidence,
)
from ai_asset_platform.reports.multicurrency_confirmed_accounting import (
    MulticurrencyConfirmedAccountingSummary,
)


JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 8, 26, 18, 0, tzinfo=JST)


def _settings(**overrides):
    values = dict(
        enable_paper_trading=True,
        enable_live_trading=False,
        live_trading_unlocked=False,
        account_currency="JPY",
        account_timezone="Asia/Tokyo",
        max_positions=5,
        max_daily_buy_orders=3,
        max_daily_sell_orders=3,
        max_daily_trading_amount_yen=1_000_000.0,
        daily_loss_limit_yen=10_000.0,
        max_consecutive_losses=3,
        max_holding_days=30,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _symbol(ticker, broker=0.0, local=0, gap=0.0):
    return SimpleNamespace(
        ticker=ticker,
        broker_quantity=broker,
        broker_average_cost=None,
        broker_market_price=None,
        local_confirmed_quantity=local,
        quantity_gap=gap,
        available_execution_count=0,
    )


def _reconciliation(**overrides):
    values = dict(
        account_ready=True,
        execution_snapshot_ready=True,
        endpoint_port=4002,
        account_currency="JPY",
        blockers=(),
        symbols=(
            _symbol("AAPL"),
            _symbol("SPY"),
            _symbol("9432.T"),
        ),
        next_action="RECONCILIATION_EVIDENCE_IS_CLEAN",
        order_sent=False,
        ledger_changed=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _open_orders(*orders, ready=True):
    return IbkrAllOpenOrdersSnapshot(
        connected=ready,
        ready=ready,
        endpoint_port=4002 if ready else None,
        orders=tuple(orders),
        errors=(),
        order_sent=False,
    )


def _accounting():
    return MulticurrencyConfirmedAccountingSummary(
        account_currency="JPY",
        confirmed_fill_count=4,
        equity_point_count=4,
        ending_cash=1_000_141.39875,
        ending_holdings=0.0,
        ending_equity=1_000_141.39875,
        realized_pnl=141.39875,
        unrealized_pnl=0.0,
        maximum_drawdown=0.0,
    )


def _runtime(**overrides):
    values = dict(
        schema_version=1,
        status="SUCCESS",
        started_at="2026-08-26T17:00:00+09:00",
        completed_at="2026-08-26T17:00:02+09:00",
        scope={"AAPL": 1, "SPY": 1, "9432.T": 100},
        ran=True,
        reason="verified Paper scan completed",
        analysis_record_count=3,
        confirmed_paper_fill_count=0,
        error_count=0,
        execution_error_count=0,
        final_decisions=[
            {"ticker": "AAPL", "final_signal": "HOLD"},
            {"ticker": "SPY", "final_signal": "HOLD"},
            {"ticker": "9432.T", "final_signal": "HOLD"},
        ],
        live_trading="PROHIBITED",
        live_order_sent=False,
    )
    values.update(overrides)
    return values


def _risk(**overrides):
    values = dict(
        account_date="2026-08-26",
        positions={},
        position_count=0,
        holding_days={},
        daily_buy_count=0,
        daily_sell_count=0,
        daily_trading_amount_account=0.0,
        daily_realized_pnl_account=0.0,
        consecutive_losses=0,
        limits={
            "max_positions": 5,
            "max_daily_buy_orders": 3,
            "max_daily_sell_orders": 3,
            "max_daily_trading_amount_account": 1_000_000.0,
            "daily_loss_limit_account": 10_000.0,
            "max_consecutive_losses": 3,
            "max_holding_days": 30,
        },
    )
    values.update(overrides)
    return values


def _evaluate(**overrides):
    values = dict(
        settings=_settings(),
        reconciliation=_reconciliation(),
        reconciliation_error=None,
        open_orders=_open_orders(),
        open_orders_error=None,
        accounting=_accounting(),
        accounting_error=None,
        risk=_risk(),
        risk_error=None,
        runtime_report=_runtime(),
        runtime_report_error=None,
        now=NOW,
        max_runtime_age_hours=96.0,
    )
    values.update(overrides)
    return module.evaluate_paper_operations(**values)


def test_complete_clean_snapshot_is_healthy():
    result = _evaluate()
    assert result.status == "HEALTHY"
    assert result.critical_reasons == ()
    assert result.warning_reasons == ()
    assert result.open_order_count == 0
    assert result.accounting_safe is True
    assert result.risk_safe is True
    assert 0.99 < result.runtime_age_hours < 1.01
    assert result.order_sent is False
    assert result.live_order_sent is False


def test_missing_first_structured_runtime_report_is_warning_not_false_success():
    result = _evaluate(runtime_report=None)
    assert result.status == "WARNING"
    assert result.critical_reasons == ()
    assert "no structured verified-runtime report" in result.warning_reasons[0]


def test_stale_runtime_report_is_warning():
    result = _evaluate(max_runtime_age_hours=0.5)
    assert result.status == "WARNING"
    assert any("stale" in item for item in result.warning_reasons)


def test_any_broker_open_order_is_critical_and_never_auto_cancelled():
    order = IbkrOpenOrderEvidence(
        order_id=88,
        symbol="SPY",
        local_symbol="SPY",
        sec_type="STK",
        currency="USD",
        exchange="SMART",
        action="BUY",
        quantity=1.0,
        order_type="LMT",
        status="Submitted",
        client_id=5,
        perm_id=999,
    )
    result = _evaluate(open_orders=_open_orders(order))
    assert result.status == "CRITICAL"
    assert result.open_order_count == 1
    assert any("manual review required" in item for item in result.critical_reasons)


def test_broker_local_gap_is_critical():
    result = _evaluate(
        reconciliation=_reconciliation(
            symbols=(
                _symbol("AAPL"),
                _symbol("SPY", broker=1.0, local=0, gap=1.0),
                _symbol("9432.T"),
            ),
            next_action="REVIEW_SPY_PAPER_POSITION_BEFORE_NEW_EXPOSURE",
        )
    )
    assert result.status == "CRITICAL"
    assert any("SPY broker/local quantity gap" in item for item in result.critical_reasons)


def test_live_unlock_is_always_critical():
    result = _evaluate(settings=_settings(live_trading_unlocked=True))
    assert result.status == "CRITICAL"
    assert "Live Trading safety lock is not intact" in result.critical_reasons


def test_failed_runtime_and_execution_errors_are_critical():
    result = _evaluate(
        runtime_report=_runtime(
            status="ERROR",
            error_count=1,
            execution_error_count=1,
        )
    )
    assert result.status == "CRITICAL"
    assert any("latest verified runtime status" in item for item in result.critical_reasons)
    assert any("analysis or execution errors" in item for item in result.critical_reasons)


def test_runtime_scope_or_decision_coverage_change_is_critical():
    result = _evaluate(
        runtime_report=_runtime(
            scope={"AAPL": 1},
            final_decisions=[{"ticker": "AAPL", "final_signal": "HOLD"}],
        )
    )
    assert result.status == "CRITICAL"
    assert any("scope differs" in item for item in result.critical_reasons)
    assert any("decisions do not cover" in item for item in result.critical_reasons)


def test_invalid_accounting_is_critical():
    result = _evaluate(accounting=None, accounting_error="missing historical FX")
    assert result.status == "CRITICAL"
    assert result.accounting_safe is False
    assert any("accounting is unsafe" in item for item in result.critical_reasons)


def test_daily_loss_or_consecutive_loss_limit_is_critical():
    result = _evaluate(
        risk=_risk(
            daily_realized_pnl_account=-10_000.0,
            consecutive_losses=3,
        )
    )
    assert result.status == "CRITICAL"
    assert any("daily realized loss limit" in item for item in result.critical_reasons)
    assert any("maximum consecutive losses" in item for item in result.critical_reasons)


def test_unverified_or_wrong_sized_position_is_critical():
    result = _evaluate(
        risk=_risk(
            positions={"MSFT": 1, "SPY": 2},
            position_count=2,
        )
    )
    assert result.status == "CRITICAL"
    assert any("unverified open position" in item for item in result.critical_reasons)
    assert any("differs from verified quantity" in item for item in result.critical_reasons)


def test_holding_time_exit_due_is_warning():
    result = _evaluate(
        risk=_risk(
            positions={"SPY": 1},
            position_count=1,
            holding_days={"SPY": 30},
        )
    )
    assert result.status == "WARNING"
    assert any("holding-time exit is due" in item for item in result.warning_reasons)


def test_risk_metrics_use_account_currency_and_account_calendar():
    records = [
        {
            "created_at": "2026-08-26T09:00:00+09:00",
            "mode": "IBKR_PAPER",
            "status": "FILLED",
            "ticker": "SPY",
            "side": "BUY",
            "shares": 1,
            "reference_price": 700.0,
            "currency": "USD",
            "fx_to_account_rate": 150.0,
            "order_intent_id": "buy",
        },
        {
            "created_at": "2026-08-26T10:00:00+09:00",
            "mode": "IBKR_PAPER",
            "status": "FILLED",
            "ticker": "SPY",
            "side": "SELL",
            "shares": 1,
            "reference_price": 701.0,
            "currency": "USD",
            "fx_to_account_rate": 150.0,
            "order_intent_id": "sell",
        },
    ]
    result = module.calculate_paper_risk_metrics(
        records,
        settings=_settings(),
        now=NOW,
    )
    assert result["account_date"] == "2026-08-26"
    assert result["daily_buy_count"] == 1
    assert result["daily_sell_count"] == 1
    assert result["daily_trading_amount_account"] == 210_150.0
    assert result["daily_realized_pnl_account"] == 150.0
    assert result["consecutive_losses"] == 0


def test_monitor_evidence_is_atomic_and_history_is_bounded(tmp_path):
    result = _evaluate()
    latest = tmp_path / "latest.json"
    history = tmp_path / "history.jsonl"
    status = tmp_path / "status.txt"
    history.write_text("x" * 100, encoding="utf-8")

    module.persist_monitor_result(
        result,
        latest_path=latest,
        history_path=history,
        status_path=status,
        max_history_bytes=50,
    )

    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["status"] == "HEALTHY"
    assert payload["monitor_order_sent"] is False
    assert history.with_suffix(".jsonl.1").read_text(encoding="utf-8") == "x" * 100
    assert len(history.read_text(encoding="utf-8").splitlines()) == 1
    assert "STATUS: HEALTHY" in status.read_text(encoding="utf-8")
    assert not latest.with_suffix(".json.tmp").exists()


def test_invalid_runtime_json_is_reported(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text("{not-json", encoding="utf-8")
    report, error = module.load_runtime_report(path)
    assert report is None
    assert error


def test_email_alert_sends_on_critical_transition_and_suppresses_repeat(tmp_path):
    critical = _evaluate(
        runtime_report=_runtime(status="ERROR", error_count=1)
    )
    sent = []
    state = tmp_path / "notification.json"
    first = module.maybe_send_monitor_email_alert(
        critical,
        sender="owner@example.com",
        app_password="secret",
        now=NOW,
        state_path=state,
        send_mail_fn=lambda *args: sent.append(args),
    )
    second = module.maybe_send_monitor_email_alert(
        critical,
        sender="owner@example.com",
        app_password="secret",
        now=datetime(2026, 8, 26, 19, 0, tzinfo=JST),
        state_path=state,
        send_mail_fn=lambda *args: sent.append(args),
    )
    assert first == "SENT"
    assert second == "UNCHANGED_SUPPRESSED"
    assert len(sent) == 1
    assert sent[0][3] == "[IBKR Paper Monitor] CRITICAL"
    assert "No order was changed" in sent[0][4]
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["status"] == "CRITICAL"
    assert "secret" not in state.read_text(encoding="utf-8")


def test_email_alert_repeats_after_bounded_cooldown(tmp_path):
    warning = _evaluate(runtime_report=None)
    sent = []
    state = tmp_path / "notification.json"
    module.maybe_send_monitor_email_alert(
        warning,
        sender="owner@example.com",
        app_password="secret",
        now=NOW,
        state_path=state,
        cooldown_hours=12,
        send_mail_fn=lambda *args: sent.append(args),
    )
    repeated = module.maybe_send_monitor_email_alert(
        warning,
        sender="owner@example.com",
        app_password="secret",
        now=datetime(2026, 8, 27, 7, 0, tzinfo=JST),
        state_path=state,
        cooldown_hours=12,
        send_mail_fn=lambda *args: sent.append(args),
    )
    assert repeated == "SENT"
    assert len(sent) == 2


def test_initial_healthy_email_state_records_baseline_without_message(tmp_path):
    sent = []
    outcome = module.maybe_send_monitor_email_alert(
        _evaluate(),
        sender="owner@example.com",
        app_password="secret",
        now=NOW,
        state_path=tmp_path / "notification.json",
        send_mail_fn=lambda *args: sent.append(args),
    )
    assert outcome == "BASELINE_RECORDED"
    assert sent == []


def test_failed_email_attempt_is_persisted_and_rate_limited(tmp_path):
    warning = _evaluate(runtime_report=None)
    state = tmp_path / "notification.json"
    attempts = []

    def fail(*args):
        attempts.append(args)
        raise RuntimeError("smtp unavailable")

    first = module.maybe_send_monitor_email_alert(
        warning,
        sender="owner@example.com",
        app_password="secret",
        now=NOW,
        state_path=state,
        cooldown_hours=12,
        send_mail_fn=fail,
    )
    second = module.maybe_send_monitor_email_alert(
        warning,
        sender="owner@example.com",
        app_password="secret",
        now=datetime(2026, 8, 26, 19, 0, tzinfo=JST),
        state_path=state,
        cooldown_hours=12,
        send_mail_fn=fail,
    )
    assert first == "ERROR: smtp unavailable"
    assert second == "UNCHANGED_SUPPRESSED"
    assert len(attempts) == 1
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["last_error"] == "smtp unavailable"
    assert payload["last_attempt_at"]


def test_email_alert_is_explicitly_not_configured_without_credentials(tmp_path):
    outcome = module.maybe_send_monitor_email_alert(
        _evaluate(runtime_report=None),
        sender="",
        app_password="",
        now=NOW,
        state_path=tmp_path / "notification.json",
        send_mail_fn=lambda *args: None,
    )
    assert outcome == "NOT_CONFIGURED"


def test_monitor_module_has_no_broker_mutation_path():
    text = Path(module.__file__).read_text(encoding="utf-8")
    assert ".placeOrder(" not in text
    assert ".cancelOrder(" not in text
    assert "AI_ASSET_VERIFIED_PAPER_RUNTIME_CONFIRM" not in text
    assert "RUN_VERIFIED_PAPER_ONLY" not in text
