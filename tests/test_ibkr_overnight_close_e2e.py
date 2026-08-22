from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import ai_asset_platform.brokers.ibkr_overnight_close_e2e as module


OPEN = datetime(2026, 8, 23, 20, 30, tzinfo=ZoneInfo("America/New_York"))


def _settings():
    return SimpleNamespace(
        enable_paper_trading=True,
        enable_ibkr_paper=True,
        enable_live_trading=False,
        live_trading_unlocked=False,
    )


def test_close_is_blocked_without_dedicated_opt_in(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.delenv("AI_ASSET_ENABLE_IBKR_OVERNIGHT_CLOSE_E2E", raising=False)
    monkeypatch.setattr(module, "preview_ibkr_paper_execution_snapshot", lambda: (_ for _ in ()).throw(AssertionError("must not query")))
    result = module.run_spy_overnight_paper_close(limit_price=760, order_log_path=tmp_path / "x", now=OPEN)
    assert result.attempted is False
    assert "opt-in" in result.reason


def test_close_requires_exactly_one_reconciled_spy(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setenv("AI_ASSET_ENABLE_IBKR_OVERNIGHT_CLOSE_E2E", "true")
    monkeypatch.setattr(module, "preview_ibkr_paper_execution_snapshot", lambda: SimpleNamespace(ready=True))
    monkeypatch.setattr(module, "reconcile_execution_snapshot_to_ledger", lambda *a, **k: SimpleNamespace(errors=()))
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [])
    monkeypatch.setattr(module, "evaluate_broker_position_guard", lambda **k: SimpleNamespace(allowed=True, local_quantity=0, broker_quantity=0, reason=""))
    result = module.run_spy_overnight_paper_close(limit_price=760, order_log_path=tmp_path / "x", now=OPEN)
    assert result.attempted is False
    assert "exactly one" in result.reason


def test_close_happy_path_is_sell_once_and_persists_broker_identity(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(module, "SETTINGS", _settings())
    monkeypatch.setenv("AI_ASSET_ENABLE_IBKR_OVERNIGHT_CLOSE_E2E", "true")
    monkeypatch.setattr(module, "preview_ibkr_paper_execution_snapshot", lambda: SimpleNamespace(ready=True))
    monkeypatch.setattr(module, "reconcile_execution_snapshot_to_ledger", lambda *a, **k: SimpleNamespace(errors=()))
    monkeypatch.setattr(module.order_manager, "load_accounting_orders", lambda: [{"ticker": "SPY"}])
    monkeypatch.setattr(module, "evaluate_broker_position_guard", lambda **k: SimpleNamespace(allowed=True, local_quantity=1, broker_quantity=1, reason=""))
    monkeypatch.setattr(module, "evaluate_verified_paper_preflight", lambda **k: SimpleNamespace(allowed=True, reason="ok"))
    monkeypatch.setattr(module, "preview_spy_overnight_close_whatif", lambda **k: SimpleNamespace(ready=True, primary_exchange="ARCA"))
    monkeypatch.setattr(module, "build_shared_risk_gate", lambda: object())
    monkeypatch.setattr(module, "_capture_account_fx_rate", lambda currency: None)
    monkeypatch.setattr(module, "_broker_exec_ids", lambda result: ["SELL-E1"])

    broker_result = SimpleNamespace(
        status="TERMINAL", sent=True, order_id=9, filled_quantity=1.0,
        avg_fill_price=760.0, executions=[{"exec_id": "SELL-E1"}],
    )
    calls = []
    class FakeBroker:
        def disconnect(self):
            calls.append("disconnect")
    class FakeService:
        def __init__(self, **kwargs):
            pass
        def execute_ibkr_paper_order(self, order, **kwargs):
            calls.append((order.side.value, order.quantity, order.limit_price, kwargs["order_intent_id"]))
            return broker_result
    monkeypatch.setattr(module, "_connect_first_available_paper_broker", lambda: FakeBroker())
    monkeypatch.setattr(module, "ExecutionService", FakeService)
    monkeypatch.setattr(module, "confirmed_fill_from_broker_result", lambda result, qty: (1.0, 760.0))
    captured = {}
    monkeypatch.setattr(module, "record_confirmed_fill", lambda **kwargs: captured.update(kwargs) or kwargs)

    result = module.run_spy_overnight_paper_close(limit_price=760, order_log_path=tmp_path / "x", now=OPEN)
    assert result.attempted is True
    assert result.confirmed_fill_persisted is True
    assert calls[0][0] == "SELL"
    assert calls[0][1:3] == (1, 760.0)
    assert captured["broker_exec_ids"] == ["SELL-E1"]
    assert captured["broker_order_id"] == 9
    assert "SELL:1" in captured["order_intent_id"]
