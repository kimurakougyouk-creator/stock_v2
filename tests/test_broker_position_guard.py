from types import SimpleNamespace

import ai_asset_platform.execution.broker_position_guard as module


def _account(*, qty=0.0, ready=True, base_currency="JPY"):
    positions = () if qty == 0 else (SimpleNamespace(symbol="SPY", quantity=qty),)
    return SimpleNamespace(ready=ready, base_currency=base_currency, positions=positions)


def test_guard_blocks_broker_local_position_mismatch(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    records = []
    result = module.evaluate_broker_position_guard(
        ticker="SPY", side="BUY", quantity=1, account=_account(qty=1), records=records
    )
    assert result.allowed is False
    assert result.local_quantity == 0
    assert result.broker_quantity == 1
    assert "mismatch" in result.reason


def test_guard_allows_flat_reconciled_buy(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    result = module.evaluate_broker_position_guard(
        ticker="SPY", side="BUY", quantity=1, account=_account(qty=0), records=[]
    )
    assert result.allowed is True


def test_guard_blocks_duplicate_buy_when_both_ledgers_hold(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    records = [{
        "status": "FILLED", "ticker": "SPY", "side": "BUY", "shares": 1,
        "order_intent_id": "x",
    }]
    result = module.evaluate_broker_position_guard(
        ticker="SPY", side="BUY", quantity=1, account=_account(qty=1), records=records
    )
    assert result.allowed is False
    assert "already held" in result.reason


def test_guard_requires_reconciled_sell_quantity(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    records = [{
        "status": "FILLED", "ticker": "SPY", "side": "BUY", "shares": 1,
        "order_intent_id": "x",
    }]
    allowed = module.evaluate_broker_position_guard(
        ticker="SPY", side="SELL", quantity=1, account=_account(qty=1), records=records
    )
    blocked = module.evaluate_broker_position_guard(
        ticker="SPY", side="SELL", quantity=2, account=_account(qty=1), records=records
    )
    assert allowed.allowed is True
    assert blocked.allowed is False


def test_guard_blocks_wrong_broker_base_currency(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    result = module.evaluate_broker_position_guard(
        ticker="SPY", side="BUY", quantity=1, account=_account(qty=0, base_currency="USD"), records=[]
    )
    assert result.allowed is False
    assert "base currency" in result.reason
