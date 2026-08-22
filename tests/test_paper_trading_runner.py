from types import SimpleNamespace

import pytest

import paper_trading_runner


def _settings(**overrides):
    values = dict(
        enable_paper_trading=True,
        enable_ibkr_paper=True,
        enable_live_trading=False,
        live_trading_unlocked=False,
        account_currency="JPY",
        trailing_stop_percent=5.0,
        max_holding_days=30,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_paper_runner_scans_without_legacy_order_branch(monkeypatch):
    calls = []
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings())
    monkeypatch.setattr(paper_trading_runner.signal_runner, "_create_configured_ai_provider", lambda: "TEST_AI")
    monkeypatch.setattr(
        paper_trading_runner.signal_runner,
        "run_signal_scan",
        lambda **kwargs: calls.append(kwargs) or {"records": [], "errors": []},
    )
    result = paper_trading_runner.run_paper_trading()
    assert result["records"] == []
    assert result["errors"] == []
    assert result["paper_orders"] == []
    assert result["execution_errors"] == []
    assert calls == [{"ai_provider": "TEST_AI", "allow_orders": False, "allow_email": False}]


def test_paper_runner_rejects_disabled_paper(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings(enable_paper_trading=False))
    with pytest.raises(RuntimeError, match="Paper Tradingが無効"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_rejects_disabled_ibkr_paper(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings(enable_ibkr_paper=False))
    with pytest.raises(RuntimeError, match="IBKR Paperが無効"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_rejects_live_unlocked(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings(live_trading_unlocked=True))
    with pytest.raises(RuntimeError, match="Live Trading"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_rejects_live_trading_enabled(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings(enable_live_trading=True))
    with pytest.raises(RuntimeError, match="Live Tradingが有効"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_main_prints_normal_health(monkeypatch, capsys):
    monkeypatch.setattr(paper_trading_runner, "run_paper_trading", lambda: {"records": [{} for _ in range(10)], "errors": []})
    paper_trading_runner.main()
    output = capsys.readouterr().out
    assert "診断結果    : NORMAL" in output
    assert "Paper Tradingは正常です。" in output
    assert "シグナル件数: 10" in output
    assert "エラー件数  : 0" in output
    assert "IBKR Pilot Qty: broker-verified per instrument" in output


def test_paper_runner_main_prints_error_health(monkeypatch, capsys):
    monkeypatch.setattr(paper_trading_runner, "run_paper_trading", lambda: {"records": [{} for _ in range(9)], "errors": ["download error"]})
    paper_trading_runner.main()
    output = capsys.readouterr().out
    assert "診断結果    : ERROR" in output
    assert "1件のエラーが発生しました。" in output
    assert "シグナル件数: 9" in output
    assert "エラー件数  : 1" in output


def test_unconfirmed_ibkr_result_exposes_observed_details():
    result = SimpleNamespace(status="NOT_SENT", sent=False, order_id=None, reached_terminal=False, timed_out=False, last_known_status=None, filled_quantity=0.0, avg_fill_price=None, message="contract rejected", errors=[{"code": 200, "message": "No security definition"}])
    execution = SimpleNamespace(attempted=True, reason="submitted", broker_result=result)
    message = paper_trading_runner._describe_unconfirmed_ibkr_result(execution)
    assert "status=NOT_SENT" in message
    assert "sent=False" in message
    assert "message=contract rejected" in message
    assert "No security definition" in message


def test_unconfirmed_ibkr_result_exposes_pre_send_stop_reason():
    execution = SimpleNamespace(attempted=False, reason="risk blocked", broker_result=None)
    assert paper_trading_runner._describe_unconfirmed_ibkr_result(execution) == "IBKR Paper注文は送信前に停止しました: risk blocked"


def _filled_execution(quantity: float, price: float = 150.0):
    broker_result = SimpleNamespace(
        sent=True,
        reached_terminal=True,
        last_known_status="Filled",
        filled_quantity=quantity,
        avg_fill_price=price,
    )
    return SimpleNamespace(attempted=True, reason="submitted", broker_result=broker_result)


def _allow_preflight(monkeypatch, *, fx=1.0):
    monkeypatch.setattr(paper_trading_runner, "_preflight_fx_rate", lambda **kwargs: fx)
    monkeypatch.setattr(
        paper_trading_runner,
        "evaluate_verified_paper_preflight",
        lambda **kwargs: SimpleNamespace(allowed=True, reason="passed"),
    )


def test_integrated_paper_pilot_uses_verified_9432_lot(monkeypatch):
    calls = []
    _allow_preflight(monkeypatch, fx=1.0)
    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", lambda **kwargs: calls.append(kwargs) or _filled_execution(100.0))
    monkeypatch.setattr(paper_trading_runner, "_sync_confirmed_fill_to_reporting", lambda: True)
    result = paper_trading_runner._execute_confirmed_ibkr_paper_order("9432.T", "BUY", 100, 150.0)
    assert calls[0]["shares"] == 100
    assert result["shares"] == 100
    assert result["paper_pilot_shares"] == 100


def test_integrated_paper_pilot_uses_verified_aapl_one_share(monkeypatch):
    calls = []
    _allow_preflight(monkeypatch, fx=150.0)
    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", lambda **kwargs: calls.append(kwargs) or _filled_execution(1.0, 300.0))
    monkeypatch.setattr(paper_trading_runner, "_sync_confirmed_fill_to_reporting", lambda: True)
    result = paper_trading_runner._execute_confirmed_ibkr_paper_order("AAPL", "BUY", 100, 300.0)
    assert calls[0]["shares"] == 1
    assert result["strategy_requested_shares"] == 100
    assert result["paper_pilot_shares"] == 1
    assert result["preflight_fx_to_account_rate"] == 150.0


def test_integrated_paper_pilot_uses_verified_spy_one_share(monkeypatch):
    calls = []
    _allow_preflight(monkeypatch, fx=150.0)
    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", lambda **kwargs: calls.append(kwargs) or _filled_execution(1.0, 700.0))
    monkeypatch.setattr(paper_trading_runner, "_sync_confirmed_fill_to_reporting", lambda: True)
    result = paper_trading_runner._execute_confirmed_ibkr_paper_order("SPY", "BUY", 100, 700.0)
    assert calls[0]["shares"] == 1
    assert result["paper_pilot_shares"] == 1


def test_preflight_block_stops_before_broker_runtime(monkeypatch):
    _allow_preflight(monkeypatch, fx=150.0)
    monkeypatch.setattr(
        paper_trading_runner,
        "evaluate_verified_paper_preflight",
        lambda **kwargs: SimpleNamespace(allowed=False, reason="allocation limit"),
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "execute_approved_signal_via_ibkr_paper",
        lambda **kwargs: pytest.fail("must not reach broker runtime"),
    )
    with pytest.raises(RuntimeError, match="allocation limit"):
        paper_trading_runner._execute_confirmed_ibkr_paper_order("SPY", "BUY", 1, 700.0)


def test_integrated_paper_pilot_blocks_unverified_symbol(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", lambda **kwargs: pytest.fail("must not reach broker runtime"))
    with pytest.raises(RuntimeError, match="not registered"):
        paper_trading_runner._execute_confirmed_ibkr_paper_order("MSFT", "BUY", 100, 500.0)


def test_integrated_paper_pilot_rejects_non_positive_requested_quantity():
    with pytest.raises(RuntimeError, match="1以上"):
        paper_trading_runner._execute_confirmed_ibkr_paper_order("9432.T", "BUY", 0, 150.0)
