from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_operator_checkpoint as module


def _whatif():
    return SimpleNamespace(
        connected=True,
        preview_received=True,
        symbol="SPY",
        primary_exchange="ARCA",
        destination="OVERNIGHT",
        quantity=1,
        limit_price=760.0,
        order_sent=False,
        margin_change="",
        commission=None,
        commission_currency=None,
        warning_text="",
        errors=(),
        ready=True,
    )


def _fx():
    return SimpleNamespace(
        connected=True,
        endpoint_port=4002,
        base_currency="USD",
        quote_currency="JPY",
        exchange="IDEALPRO",
        bid=None,
        ask=None,
        rate=150.0,
        source="HISTORICAL_MIDPOINT",
        order_sent=False,
        errors=("10197",),
        ready=True,
    )


def _accounting():
    return SimpleNamespace(
        account_currency="JPY",
        confirmed_fill_count=0,
        equity_point_count=0,
        ending_equity=1000000.0,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
        maximum_drawdown=0.0,
    )


def _preflight():
    return SimpleNamespace(
        allowed=True,
        reason="passed",
        planned_notional_account=114000.0,
        held_quantity=0,
        current_position_count=0,
        daily_trading_amount_account=0.0,
    )


def test_checkpoint_accepts_broker_historical_fx_evidence(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", lambda **kwargs: _preflight())

    result = module.run_ibkr_operator_checkpoint(limit_price=760.0)

    assert result.fx.ready is True
    assert result.fx.source == "HISTORICAL_MIDPOINT"
    assert result.preflight.allowed is True
    assert result.ready_for_paper_e2e_review is True
