from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_operator_checkpoint as module


def _whatif(*, ready=True):
    return SimpleNamespace(
        connected=ready,
        preview_received=ready,
        symbol="SPY",
        primary_exchange="ARCA" if ready else None,
        destination="OVERNIGHT" if ready else None,
        quantity=1,
        limit_price=768.0,
        order_sent=False,
        margin_change="0" if ready else None,
        commission=0.01 if ready else None,
        commission_currency="USD" if ready else None,
        warning_text="",
        errors=(),
        ready=ready,
    )


def _fx(*, ready=True):
    return SimpleNamespace(
        connected=ready,
        endpoint_port=4002 if ready else None,
        base_currency="USD",
        quote_currency="JPY",
        exchange="IDEALPRO",
        bid=150.0 if ready else None,
        ask=150.2 if ready else None,
        rate=150.1 if ready else None,
        source="MARKET_DATA",
        order_sent=False,
        errors=(),
        ready=ready,
    )


def _accounting():
    return SimpleNamespace(
        account_currency="JPY",
        confirmed_fill_count=2,
        equity_point_count=2,
        ending_equity=1000200.0,
        realized_pnl=100.0,
        unrealized_pnl=100.0,
        maximum_drawdown=0.0,
    )


def _preflight(*, allowed=True, reason="passed"):
    return SimpleNamespace(
        allowed=allowed,
        reason=reason,
        planned_notional_account=115276.8,
        held_quantity=0,
        current_position_count=0,
        daily_trading_amount_account=0.0,
    )


def _settings():
    return SimpleNamespace(account_currency="JPY")


def test_checkpoint_combines_accounting_whatif_fx_and_preflight(monkeypatch):
    seen = {"whatif": 0, "fx": 0, "accounting": 0, "preflight": 0}
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])

    def fake_whatif(*, limit_price):
        seen["whatif"] += 1
        assert limit_price == 768.0
        return _whatif()

    def fake_fx(**kwargs):
        seen["fx"] += 1
        assert kwargs == {"base_currency": "USD", "quote_currency": "JPY"}
        return _fx()

    def fake_accounting(records, *, initial_capital, account_currency):
        seen["accounting"] += 1
        assert records == []
        assert initial_capital == float(module.TRADING_CAPITAL)
        assert account_currency == "JPY"
        return _accounting()

    def fake_preflight(**kwargs):
        seen["preflight"] += 1
        assert kwargs["fx_to_account_rate"] == 150.1
        return _preflight()

    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", fake_whatif)
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", fake_fx)
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", fake_accounting)
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", fake_preflight)

    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert seen == {"whatif": 1, "fx": 1, "accounting": 1, "preflight": 1}
    assert result.ready_for_paper_e2e_review is True
    assert result.whatif.order_sent is False
    assert result.fx.order_sent is False
    assert result.accounting_error is None
    assert result.preflight_error is None
    assert result.spy_confirmed_held_quantity == 0
    assert result.legacy_evidence_blockers == ()


def test_checkpoint_never_marks_ready_when_whatif_fails(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif(ready=False))
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", lambda **kwargs: _preflight())
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert result.whatif.order_sent is False


def test_checkpoint_blocks_readiness_when_fx_evidence_fails(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx(ready=False))
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    called = {"preflight": 0}
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", lambda **kwargs: called.__setitem__("preflight", 1))
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert "FX evidence" in result.preflight_error
    assert called["preflight"] == 0


def test_checkpoint_reports_missing_historical_fx_evidence(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    rows = [{
        "mode": "IBKR_PAPER",
        "status": "FILLED",
        "ticker": "AAPL",
        "side": "BUY",
        "shares": 1,
        "currency": "USD",
        "order_intent_id": "old-aapl-fill",
    }]
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: rows)
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())

    def unsafe(*args, **kwargs):
        raise module.MulticurrencyConfirmedAccountingError(
            "confirmed fill currency USD requires explicit fx_to_account_rate into JPY"
        )

    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", unsafe)
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert "old-aapl-fill" in result.accounting_error
    assert "missing-historical-fx" in result.accounting_error
    assert result.preflight is None
    assert "legacy confirmed-fill evidence" in result.preflight_error


def test_checkpoint_reports_missing_currency_without_guessing(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    rows = [{
        "mode": "IBKR_PAPER",
        "status": "FILLED",
        "ticker": "AAPL",
        "side": "BUY",
        "shares": 1,
        "order_intent_id": "legacy-no-currency",
    }]
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: rows)
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    monkeypatch.setattr(
        module,
        "audit_multicurrency_confirmed_accounting",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            module.MulticurrencyConfirmedAccountingError("IBKR_PAPER confirmed fill is missing currency")
        ),
    )
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert "missing-currency" in result.accounting_error
    assert "legacy-no-currency" in result.accounting_error


def test_existing_spy_confirmed_fill_blocks_duplicate_buy_even_when_accounting_unsafe(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    rows = [{
        "mode": "IBKR_PAPER",
        "status": "FILLED",
        "ticker": "SPY",
        "side": "BUY",
        "shares": 1,
        "reference_price": 765.45,
        "order_intent_id": "old-spy-fill",
    }]
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: rows)
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    monkeypatch.setattr(
        module,
        "audit_multicurrency_confirmed_accounting",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            module.MulticurrencyConfirmedAccountingError("missing currency")
        ),
    )
    called = {"preflight": 0}
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", lambda **kwargs: called.__setitem__("preflight", 1))

    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.spy_confirmed_held_quantity == 1
    assert result.ready_for_paper_e2e_review is False
    assert "already has 1 confirmed share" in result.preflight_error
    assert called["preflight"] == 0


def test_checkpoint_blocks_when_position_preflight_blocks(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    monkeypatch.setattr(
        module,
        "evaluate_verified_paper_preflight",
        lambda **kwargs: _preflight(allowed=False, reason="new BUY blocked because the symbol is already held"),
    )
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert "already held" in result.preflight_error
