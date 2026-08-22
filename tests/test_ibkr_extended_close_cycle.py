from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_extended_close_cycle as module


def test_extended_close_cycle_does_not_call_close_when_plan_not_ready(monkeypatch):
    monkeypatch.setattr(module, "preview_ibkr_paper_account_snapshot", lambda: SimpleNamespace(ready=False, positions=()))
    called = {"close": False}

    def _close(**kwargs):
        called["close"] = True
        raise AssertionError("close should not be called")

    monkeypatch.setattr(module, "run_spy_extended_paper_close", _close)
    plan, result = module.run_extended_close_cycle()
    assert not plan.ready
    assert result is None
    assert called["close"] is False
