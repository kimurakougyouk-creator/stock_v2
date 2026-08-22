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


def _broker_account(*, ready=True, base_currency="JPY", positions=()):
    return SimpleNamespace(
        connected=ready,
        endpoint_port=4002 if ready else None,
        account_id="DU123" if ready else None,
        account_ready=ready,
        base_currency=base_currency if ready else None,
        net_liquidation=1_000_000.0 if ready else None,
        available_funds=900_000.0 if ready else None,
        gross_position_value=100_000.0 if ready else None,
        total_cash_value=900_000.0 if ready else None,
        positions=tuple(positions),
        order_sent=False,
        errors=(),
        ready=ready,
    )


def _position(symbol, quantity):
    return SimpleNamespace(symbol=symbol, quantity=quantity)


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


def _wire_safe_broker(monkeypatch):
    monkeypatch.setattr(module, "preview_ibkr_paper_account_snapshot", lambda: _broker_account())


def test_checkpoint_combines_accounting_whatif_fx_broker_and_preflight(monkeypatch):
    seen = {"whatif": 0, "fx": 0, "accounting": 0, "preflight": 0}
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    _wire_safe_broker(monkeypatch)

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
    assert result.account.ready is True
    assert result.reconciliation_error is None
    assert result.broker_spy_held_quantity == 0


def test_legacy_fill_missing_currency_is_quarantined_but_still_blocks_new_buy(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    rows = [{
        "mode": "IBKR_PAPER", "status": "FILLED", "ticker": "AAPL",
        "side": "BUY", "shares": 1, "reference_price": 308.98,
        "order_intent_id": "legacy-no-currency",
    }]
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: rows)
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    _wire_safe_broker(monkeypatch)
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda records, **kwargs: _accounting())
    called = {"preflight": 0}
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", lambda **kwargs: called.__setitem__("preflight", 1))

    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert result.quarantined_legacy_fill_count == 1
    assert result.legacy_evidence_blockers == ("AAPL:legacy-no-currency:missing-currency",)
    assert "legacy confirmed-fill evidence" in result.preflight_error
    assert called["preflight"] == 0


def test_broker_spy_position_blocks_duplicate_buy_even_when_local_ledger_is_empty(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_account_snapshot",
        lambda: _broker_account(positions=(_position("SPY", 1.0),)),
    )
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    called = {"preflight": 0}
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", lambda **kwargs: called.__setitem__("preflight", 1))
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.broker_spy_held_quantity == 1.0
    assert result.ready_for_paper_e2e_review is False
    assert "broker/local position reconciliation" in result.preflight_error
    assert "local/broker SPY position mismatch" in result.reconciliation_error
    assert called["preflight"] == 0


def test_configured_currency_must_match_broker_base_currency(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    monkeypatch.setattr(module, "preview_ibkr_paper_account_snapshot", lambda: _broker_account(base_currency="USD"))
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert "does not match" in result.reconciliation_error
    assert "broker/local position reconciliation" in result.preflight_error


def test_existing_local_spy_confirmed_fill_requires_broker_match_then_blocks_duplicate_buy(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    rows = [{
        "mode": "IBKR_PAPER", "status": "FILLED", "ticker": "SPY",
        "side": "BUY", "shares": 1, "reference_price": 765.45,
        "currency": "USD", "fx_to_account_rate": 150.0,
        "order_intent_id": "old-spy-fill",
    }]
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: rows)
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_account_snapshot",
        lambda: _broker_account(positions=(_position("SPY", 1.0),)),
    )
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.spy_confirmed_held_quantity == 1
    assert result.broker_spy_held_quantity == 1.0
    assert result.reconciliation_error is None
    assert result.ready_for_paper_e2e_review is False
    assert "already has 1 confirmed share" in result.preflight_error


def test_checkpoint_never_marks_ready_when_whatif_fails(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif(ready=False))
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    _wire_safe_broker(monkeypatch)
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", lambda **kwargs: _preflight())
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False


def test_checkpoint_blocks_readiness_when_fx_evidence_fails(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx(ready=False))
    _wire_safe_broker(monkeypatch)
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert "FX evidence" in result.preflight_error


def test_checkpoint_blocks_when_position_preflight_blocks(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", lambda **kwargs: _whatif())
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _fx())
    _wire_safe_broker(monkeypatch)
    monkeypatch.setattr(module, "audit_multicurrency_confirmed_accounting", lambda *args, **kwargs: _accounting())
    monkeypatch.setattr(
        module,
        "evaluate_verified_paper_preflight",
        lambda **kwargs: _preflight(allowed=False, reason="new BUY blocked because the symbol is already held"),
    )
    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert "already held" in result.preflight_error
