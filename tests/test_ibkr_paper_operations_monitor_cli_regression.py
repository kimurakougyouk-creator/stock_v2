from ai_asset_platform.brokers import ibkr_paper_operations_monitor as module


def test_main_reports_unavailable_risk_without_crashing(monkeypatch, capsys):
    result = module.PaperOperationsMonitorResult(
        status="CRITICAL",
        checked_at="2026-08-27T01:40:00+09:00",
        critical_reasons=("active risk metrics are unavailable",),
        warning_reasons=(),
        account_ready=False,
        execution_snapshot_ready=False,
        endpoint_port=None,
        account_currency=None,
        reconciliation_next_action=None,
        reconciliation_blocker_count=0,
        symbols=(),
        open_orders_ready=False,
        open_order_count=0,
        open_orders=(),
        accounting_safe=False,
        accounting=None,
        risk_safe=False,
        risk=None,
        runtime_report_present=False,
        runtime_status=None,
        runtime_age_hours=None,
        runtime=None,
        order_sent=False,
        live_order_sent=False,
    )

    monkeypatch.setenv("IBKR_PAPER_MONITOR_EMAIL_ALERTS", "off")
    monkeypatch.setattr(
        module,
        "run_paper_operations_monitor_once",
        lambda **kwargs: result,
    )
    monkeypatch.setattr(
        module,
        "persist_monitor_result",
        lambda *args, **kwargs: None,
    )

    assert module.main() == 2
    output = capsys.readouterr().out
    assert "RISK SAFE             : False" in output
    assert "CONSECUTIVE LOSSES    : UNAVAILABLE" in output
    assert "MONITOR ORDER SENT    : False" in output
    assert "LIVE ORDER SENT       : False" in output
