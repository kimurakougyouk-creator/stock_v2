from types import SimpleNamespace

import ai_asset_platform.execution.verified_paper_scan as module


def _record(ticker="SPY", signal="BUY", price=700.0):
    return {"Ticker": ticker, "FinalSignal": signal, "Close": price}


def _settings(**overrides):
    values = dict(trailing_stop_percent=5.0, max_holding_days=30)
    values.update(overrides)
    return SimpleNamespace(**values)


def test_buy_uses_broker_verified_quantity_not_legacy_reference_shares(monkeypatch):
    monkeypatch.setattr(module.order_manager, "get_open_positions", lambda: {})
    monkeypatch.setattr(module, "verified_paper_test_quantity_for_ticker", lambda ticker: 1)
    calls = []
    result = module.execute_verified_actions_from_scan(
        {"records": [_record()], "errors": []},
        execute_order=lambda *args: calls.append(args) or {"status": "FILLED"},
        settings=_settings(),
    )
    assert calls == [("SPY", "BUY", 1, 700.0)]
    assert result["paper_orders"][0]["status"] == "FILLED"


def test_existing_position_blocks_new_buy_before_executor(monkeypatch):
    monkeypatch.setattr(module.order_manager, "get_open_positions", lambda: {"SPY": 1})
    monkeypatch.setattr(module.order_manager, "update_trailing_high_price", lambda *a, **k: 700.0)
    monkeypatch.setattr(module.order_manager, "calculate_position_holding_days", lambda ticker: 1)
    monkeypatch.setattr(module.signal_runner, "evaluate_trailing_stop", lambda **kwargs: (False, 0.0))
    monkeypatch.setattr(module, "verified_paper_test_quantity_for_ticker", lambda ticker: 1)
    called = []
    result = module.execute_verified_actions_from_scan(
        {"records": [_record(signal="BUY")], "errors": []},
        execute_order=lambda *args: called.append(args),
        settings=_settings(),
    )
    assert called == []
    assert result["paper_orders"] == []


def test_sell_without_position_is_skipped(monkeypatch):
    monkeypatch.setattr(module.order_manager, "get_open_positions", lambda: {})
    called = []
    result = module.execute_verified_actions_from_scan(
        {"records": [_record(signal="SELL")], "errors": []},
        execute_order=lambda *args: called.append(args),
        settings=_settings(),
    )
    assert called == []
    assert result["execution_errors"] == []


def test_trailing_stop_forces_verified_sell(monkeypatch):
    monkeypatch.setattr(module.order_manager, "get_open_positions", lambda: {"SPY": 1})
    monkeypatch.setattr(module.order_manager, "update_trailing_high_price", lambda *a, **k: 800.0)
    monkeypatch.setattr(module.order_manager, "calculate_position_holding_days", lambda ticker: 1)
    monkeypatch.setattr(module.signal_runner, "evaluate_trailing_stop", lambda **kwargs: (True, 12.5))
    monkeypatch.setattr(module, "verified_paper_test_quantity_for_ticker", lambda ticker: 1)
    calls = []
    result = module.execute_verified_actions_from_scan(
        {"records": [_record(signal="HOLD", price=700.0)], "errors": []},
        execute_order=lambda *args: calls.append(args) or {"status": "FILLED"},
        settings=_settings(),
    )
    assert calls == [("SPY", "SELL", 1, 700.0)]
    assert result["paper_orders"][0]["forced_exit"] is True


def test_time_stop_forces_verified_sell(monkeypatch):
    monkeypatch.setattr(module.order_manager, "get_open_positions", lambda: {"9432.T": 100})
    monkeypatch.setattr(module.order_manager, "update_trailing_high_price", lambda *a, **k: 160.0)
    monkeypatch.setattr(module.order_manager, "calculate_position_holding_days", lambda ticker: 31)
    monkeypatch.setattr(module.signal_runner, "evaluate_trailing_stop", lambda **kwargs: (False, 0.0))
    monkeypatch.setattr(module, "verified_paper_test_quantity_for_ticker", lambda ticker: 100)
    calls = []
    result = module.execute_verified_actions_from_scan(
        {"records": [_record(ticker="9432.T", signal="HOLD", price=150.0)], "errors": []},
        execute_order=lambda *args: calls.append(args) or {"status": "FILLED"},
        settings=_settings(),
    )
    assert calls == [("9432.T", "SELL", 100, 150.0)]
    assert result["paper_orders"][0]["forced_exit"] is True


def test_unverified_symbol_never_reaches_executor(monkeypatch):
    monkeypatch.setattr(module.order_manager, "get_open_positions", lambda: {})
    monkeypatch.setattr(module, "verified_paper_test_quantity_for_ticker", lambda ticker: None)
    called = []
    result = module.execute_verified_actions_from_scan(
        {"records": [_record(ticker="MSFT")], "errors": []},
        execute_order=lambda *args: called.append(args),
        settings=_settings(),
    )
    assert called == []
    assert "not registered" in result["execution_errors"][0]["error"]


def test_verified_sell_quantity_larger_than_holdings_is_blocked(monkeypatch):
    monkeypatch.setattr(module.order_manager, "get_open_positions", lambda: {"9432.T": 50})
    monkeypatch.setattr(module.order_manager, "update_trailing_high_price", lambda *a, **k: 150.0)
    monkeypatch.setattr(module.order_manager, "calculate_position_holding_days", lambda ticker: 1)
    monkeypatch.setattr(module.signal_runner, "evaluate_trailing_stop", lambda **kwargs: (False, 0.0))
    monkeypatch.setattr(module, "verified_paper_test_quantity_for_ticker", lambda ticker: 100)
    called = []
    result = module.execute_verified_actions_from_scan(
        {"records": [_record(ticker="9432.T", signal="SELL", price=150.0)], "errors": []},
        execute_order=lambda *args: called.append(args),
        settings=_settings(),
    )
    assert called == []
    assert "smaller" in result["execution_errors"][0]["error"]


def test_executor_failure_is_collected_and_never_retried(monkeypatch):
    monkeypatch.setattr(module.order_manager, "get_open_positions", lambda: {})
    monkeypatch.setattr(module, "verified_paper_test_quantity_for_ticker", lambda ticker: 1)
    calls = {"count": 0}
    def fail(*args):
        calls["count"] += 1
        raise RuntimeError("uncertain broker state")
    result = module.execute_verified_actions_from_scan(
        {"records": [_record()], "errors": []},
        execute_order=fail,
        settings=_settings(),
    )
    assert calls["count"] == 1
    assert result["paper_orders"] == []
    assert "uncertain broker state" in result["execution_errors"][0]["error"]
