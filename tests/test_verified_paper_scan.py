from types import SimpleNamespace

import ai_asset_platform.execution.verified_paper_scan as module


def _record(
    ticker="SPY",
    signal="BUY",
    price=700.0,
    source_sha="a" * 40,
    parameters_sha="b" * 64,
):
    return {
        "Ticker": ticker,
        "FinalSignal": signal,
        "Close": price,
        "StrategySourceSHA": source_sha,
        "StrategyParametersSHA": parameters_sha,
    }


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
    assert calls == [("SPY", "BUY", 1, 700.0, "a" * 40, "b" * 64)]
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
    assert calls == [("SPY", "SELL", 1, 700.0, "a" * 40, "b" * 64)]
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
    assert calls == [("9432.T", "SELL", 100, 150.0, "a" * 40, "b" * 64)]
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


def test_classify_paper_execution_error_market_session_blocked():
    message = (
        "verified Paper market-session guard blocked order: "
        "market closed / venue=NASDAQ / local=2026-10-29T10:00:00"
    )
    assert module.classify_paper_execution_error(message) == (
        module.EXECUTION_ERROR_CLASS_MARKET_SESSION_BLOCKED
    )


def test_classify_paper_execution_error_fx_evidence_unavailable():
    message = "USD->JPY broker FX evidence is unavailable; BUY blocked"
    assert module.classify_paper_execution_error(message) == (
        module.EXECUTION_ERROR_CLASS_FX_EVIDENCE_UNAVAILABLE
    )


def test_classify_paper_execution_error_preflight_blocked():
    assert module.classify_paper_execution_error(
        "verified Paper preflight blocked order: allocation limit"
    ) == module.EXECUTION_ERROR_CLASS_PREFLIGHT_BLOCKED
    assert module.classify_paper_execution_error(
        "verified Paper preflight failed: bad evidence"
    ) == module.EXECUTION_ERROR_CLASS_PREFLIGHT_BLOCKED


def test_classify_paper_execution_error_quantity_not_registered():
    assert module.classify_paper_execution_error(
        "broker-verified Paper quantity is not registered"
    ) == module.EXECUTION_ERROR_CLASS_QUANTITY_NOT_REGISTERED
    assert module.classify_paper_execution_error(
        "broker-verified Paper quantity is invalid"
    ) == module.EXECUTION_ERROR_CLASS_QUANTITY_NOT_REGISTERED


def test_classify_paper_execution_error_negative_position():
    assert module.classify_paper_execution_error(
        "confirmed ledger contains a negative position; execution blocked"
    ) == module.EXECUTION_ERROR_CLASS_NEGATIVE_POSITION


def test_classify_paper_execution_error_insufficient_holdings():
    assert module.classify_paper_execution_error(
        "confirmed holdings are smaller than the broker-verified Paper SELL quantity"
    ) == module.EXECUTION_ERROR_CLASS_INSUFFICIENT_HOLDINGS


def test_classify_paper_execution_error_invalid_reference_price():
    assert module.classify_paper_execution_error(
        "actionable signal has no positive reference price"
    ) == module.EXECUTION_ERROR_CLASS_INVALID_REFERENCE_PRICE


def test_classify_paper_execution_error_holding_age_error():
    assert module.classify_paper_execution_error(
        "confirmed holding age cannot be reconstructed safely: KeyError('x')"
    ) == module.EXECUTION_ERROR_CLASS_HOLDING_AGE_ERROR


def test_classify_paper_execution_error_broker_fill_unconfirmed():
    assert module.classify_paper_execution_error(
        "IBKR PaperでFilledを確認できなかったため、注文済みとして記録しません。status=NOT_SENT"
    ) == module.EXECUTION_ERROR_CLASS_BROKER_FILL_UNCONFIRMED
    assert module.classify_paper_execution_error(
        "IBKR Paper注文は送信前に停止しました: risk blocked"
    ) == module.EXECUTION_ERROR_CLASS_BROKER_FILL_UNCONFIRMED


def test_classify_paper_execution_error_unknown_falls_back_without_leaking_text():
    label = module.classify_paper_execution_error("No security definition has been found")
    assert label == module.EXECUTION_ERROR_CLASS_UNKNOWN_ERROR
    assert "No security definition" not in label
