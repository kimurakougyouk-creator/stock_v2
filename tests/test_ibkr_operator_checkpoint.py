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


def _accounting():
    return SimpleNamespace(
        confirmed_fill_count=2,
        equity_point_count=2,
        ending_equity=1000200.0,
        realized_pnl=100.0,
        unrealized_pnl=100.0,
        maximum_drawdown=0.0,
    )


def test_checkpoint_combines_local_accounting_and_single_whatif(monkeypatch):
    seen = {"preview": 0, "accounting": 0}

    def fake_preview(*, limit_price):
        seen["preview"] += 1
        assert limit_price == 768.0
        return _whatif()

    def fake_accounting(path, *, initial_capital):
        seen["accounting"] += 1
        assert path == module.order_manager.ORDER_LOG_PATH
        assert initial_capital == float(module.TRADING_CAPITAL)
        return _accounting()

    monkeypatch.setattr(module, "preview_ibkr_paper_overnight_order", fake_preview)
    monkeypatch.setattr(module, "audit_confirmed_accounting_file", fake_accounting)

    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert seen == {"preview": 1, "accounting": 1}
    assert result.ready_for_paper_e2e_review is True
    assert result.whatif.order_sent is False
    assert result.accounting.confirmed_fill_count == 2


def test_checkpoint_never_marks_ready_when_whatif_fails(monkeypatch):
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_overnight_order",
        lambda **kwargs: _whatif(ready=False),
    )
    monkeypatch.setattr(
        module,
        "audit_confirmed_accounting_file",
        lambda *args, **kwargs: _accounting(),
    )

    result = module.run_ibkr_operator_checkpoint(limit_price=768.0)
    assert result.ready_for_paper_e2e_review is False
    assert result.whatif.order_sent is False
