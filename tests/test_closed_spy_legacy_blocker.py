from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_operator_checkpoint as module


def _whatif():
    return SimpleNamespace(
        connected=True, preview_received=True, symbol="SPY", primary_exchange="ARCA",
        destination="OVERNIGHT", quantity=1, limit_price=760.0, order_sent=False,
        warning_text="", errors=(), ready=True,
    )


def _fx():
    return SimpleNamespace(
        connected=True, endpoint_port=4002, base_currency="USD", quote_currency="JPY",
        exchange="IDEALPRO", bid=158.8, ask=158.9, rate=158.85,
        source="MARKET_DATA", order_sent=False, errors=(), ready=True,
    )


def _account():
    return SimpleNamespace(
        connected=True, endpoint_port=4002, account_id="DU123", account_ready=True,
        base_currency="JPY", net_liquidation=1_000_000.0, available_funds=900_000.0,
        gross_position_value=0.0, total_cash_value=1_000_000.0, positions=(),
        order_sent=False, errors=(), ready=True,
    )


def _accounting():
    return SimpleNamespace(
        account_currency="JPY", confirmed_fill_count=2, equity_point_count=2,
        ending_equity=1_000_140.0, realized_pnl=140.0, unrealized_pnl=0.0,
        maximum_drawdown=0.0,
    )


def _preflight():
    return SimpleNamespace(
        allowed=True, reason="passed", planned_notional_account=120000.0,
        held_quantity=0, current_position_count=0, daily_trading_amount_account=0.0,
    )


def test_closed_spy_round_trip_does_not_leave_spy_legacy_blocker(monkeypatch):
    rows = [
        {
            "mode": "IBKR_PAPER", "status": "FILLED", "ticker": "SPY",
            "side": "BUY", "shares": 1, "reference_price": 765.45,
            "currency": "USD", "order_intent_id": "broker-recovery:buy",
            "broker_exec_ids": ["BUY_EXEC"],
        },
        {
            "mode": "IBKR_PAPER", "status": "FILLED", "ticker": "SPY",
            "side": "SELL", "shares": 1, "reference_price": 766.34,
            "currency": "USD", "order_intent_id": "overnight-close",
            "broker_exec_ids": ["SELL_EXEC"], "fx_to_account_rate": 158.8725,
        },
        {
            "mode": "IBKR_PAPER", "status": "FILLED", "ticker": "AAPL",
            "side": "BUY", "shares": 1, "reference_price": 308.98,
            "order_intent_id": "legacy-aapl",
        },
    ]
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: rows)
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    monkeypatch.setattr(module, "preview_ibkr_paper_account_snapshot", lambda: _account())
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", lambda **kwargs: _preflight())

    result = module.run_ibkr_operator_checkpoint(limit_price=760.0)

    assert result.spy_confirmed_held_quantity == 0
    assert all(not blocker.startswith("SPY:") for blocker in result.legacy_evidence_blockers)
    assert result.legacy_evidence_blockers == ("AAPL:legacy-aapl:missing-currency",)
    assert result.preflight_error == "legacy confirmed-fill evidence is incomplete; new BUY remains blocked"
