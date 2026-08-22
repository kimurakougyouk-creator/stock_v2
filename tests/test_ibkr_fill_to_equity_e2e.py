import json
from types import SimpleNamespace

import order_manager
import paper_trading_runner


def _filled_result(quantity=1.0, price=100.0):
    broker_result = SimpleNamespace(
        sent=True,
        reached_terminal=True,
        last_known_status="Filled",
        filled_quantity=quantity,
        avg_fill_price=price,
    )
    return SimpleNamespace(attempted=True, broker_result=broker_result)


def _set_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(order_manager, "ORDER_LOG_DIR", tmp_path)
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", tmp_path / "paper_orders.jsonl")
    monkeypatch.setattr(order_manager, "TRADE_PNL_PATH", tmp_path / "paper_trade_pnls.json")


def test_usd_confirmed_fill_with_fx_updates_jpy_equity_reporting(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)

    def fake_execute(**kwargs):
        from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
        record_confirmed_fill(
            ticker=kwargs["ticker"], side=kwargs["signal"], filled_quantity=1,
            avg_fill_price=100.0, currency="USD", fx_to_account_rate=150.0,
            order_intent_id=kwargs["order_intent_id"],
            order_log_path=kwargs["order_log_path"],
        )
        return _filled_result()

    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", fake_execute)
    result = paper_trading_runner._execute_confirmed_ibkr_paper_order("AAPL", "BUY", 1, 100.0)

    assert result["status"] == "FILLED"
    assert result["currency"] == "USD"
    assert result["reporting_safe"] is True
    assert not (tmp_path / "paper_trade_pnls.json").exists()
    assert (tmp_path / "equity_history.csv").exists()
    assert (tmp_path / "paper_drawdown.json").exists()
    summary = json.loads((tmp_path / "paper_accounting_summary.json").read_text(encoding="utf-8"))
    assert summary["account_currency"] == "JPY"
    assert summary["cross_currency"] is True
    assert summary["ending_cash"] == 985000.0
    assert summary["ending_holdings"] == 15000.0
    assert summary["ending_equity"] == 1000000.0
    status = json.loads((tmp_path / "paper_accounting_status.json").read_text(encoding="utf-8"))
    assert status == {"safe": True, "reason": None}


def test_usd_confirmed_fill_without_fx_remains_fail_closed(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)

    def fake_execute(**kwargs):
        from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
        record_confirmed_fill(
            ticker=kwargs["ticker"], side=kwargs["signal"], filled_quantity=1,
            avg_fill_price=100.0, currency="USD",
            order_intent_id=kwargs["order_intent_id"],
            order_log_path=kwargs["order_log_path"],
        )
        return _filled_result()

    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", fake_execute)
    result = paper_trading_runner._execute_confirmed_ibkr_paper_order("AAPL", "BUY", 1, 100.0)
    assert result["reporting_safe"] is False
    assert not (tmp_path / "equity_history.csv").exists()
    status = json.loads((tmp_path / "paper_accounting_status.json").read_text(encoding="utf-8"))
    assert status["safe"] is False
    assert "fx_to_account_rate" in status["reason"]


def test_jpy_confirmed_fill_still_updates_legacy_and_new_summary(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)

    def fake_execute(**kwargs):
        from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
        record_confirmed_fill(
            ticker=kwargs["ticker"], side=kwargs["signal"], filled_quantity=100,
            avg_fill_price=100.0, currency="JPY", fx_to_account_rate=1.0,
            order_intent_id=kwargs["order_intent_id"],
            order_log_path=kwargs["order_log_path"],
        )
        return _filled_result(quantity=100.0, price=100.0)

    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", fake_execute)
    result = paper_trading_runner._execute_confirmed_ibkr_paper_order("9432.T", "BUY", 100, 100.0)

    assert result["reporting_safe"] is True
    assert result["currency"] == "JPY"
    assert (tmp_path / "paper_trade_pnls.json").exists()
    assert (tmp_path / "paper_accounting_summary.json").exists()
    assert (tmp_path / "equity_history.csv").exists()
    drawdown = json.loads((tmp_path / "paper_drawdown.json").read_text(encoding="utf-8"))
    assert drawdown == {
        "maximum_drawdown": 0.0,
        "equity_points": 1,
        "account_currency": "JPY",
    }


def test_reexecution_same_session_intent_does_not_double_count(monkeypatch, tmp_path):
    _set_paths(monkeypatch, tmp_path)

    def fake_execute(**kwargs):
        from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
        record_confirmed_fill(
            ticker=kwargs["ticker"], side=kwargs["signal"], filled_quantity=1,
            avg_fill_price=100.0, currency="USD", fx_to_account_rate=150.0,
            order_intent_id=kwargs["order_intent_id"],
            order_log_path=kwargs["order_log_path"],
        )
        return _filled_result()

    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", fake_execute)
    first = paper_trading_runner._execute_confirmed_ibkr_paper_order("AAPL", "BUY", 1, 100.0)
    second = paper_trading_runner._execute_confirmed_ibkr_paper_order("AAPL", "BUY", 1, 101.0)

    lines = (tmp_path / "paper_orders.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    assert first["order_intent_id"] == second["order_intent_id"]
    assert first["reporting_safe"] is True
    assert second["reporting_safe"] is True
