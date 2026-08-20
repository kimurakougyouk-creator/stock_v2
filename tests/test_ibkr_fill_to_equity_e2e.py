import json
from types import SimpleNamespace

import order_manager
import paper_trading_runner


def _filled_result():
    broker_result = SimpleNamespace(
        sent=True,
        reached_terminal=True,
        last_known_status="Filled",
        filled_quantity=1.0,
        avg_fill_price=100.0,
    )
    return SimpleNamespace(attempted=True, broker_result=broker_result)


def test_confirmed_ibkr_fill_updates_trade_equity_and_drawdown_reporting(monkeypatch, tmp_path):
    monkeypatch.setattr(order_manager, "ORDER_LOG_DIR", tmp_path)
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", tmp_path / "paper_orders.jsonl")
    monkeypatch.setattr(order_manager, "TRADE_PNL_PATH", tmp_path / "paper_trade_pnls.json")

    def fake_execute(**kwargs):
        from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
        record_confirmed_fill(
            ticker=kwargs["ticker"], side=kwargs["signal"], filled_quantity=1,
            avg_fill_price=100.0, order_intent_id=kwargs["order_intent_id"],
            order_log_path=kwargs["order_log_path"],
        )
        return _filled_result()

    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", fake_execute)
    paper_trading_runner._execute_confirmed_ibkr_paper_order("AAPL", "BUY", 1, 100.0)
    assert (tmp_path / "paper_trade_pnls.json").exists()
    assert (tmp_path / "equity_history.csv").exists()
    drawdown_path = tmp_path / "paper_drawdown.json"
    assert drawdown_path.exists()
    drawdown = json.loads(drawdown_path.read_text(encoding="utf-8"))
    assert drawdown == {"maximum_drawdown": 0.0, "equity_points": 1}


def test_reexecution_same_intent_does_not_double_count(monkeypatch, tmp_path):
    monkeypatch.setattr(order_manager, "ORDER_LOG_DIR", tmp_path)
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", tmp_path / "paper_orders.jsonl")
    monkeypatch.setattr(order_manager, "TRADE_PNL_PATH", tmp_path / "paper_trade_pnls.json")

    def fake_execute(**kwargs):
        from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
        record_confirmed_fill(
            ticker=kwargs["ticker"], side=kwargs["signal"], filled_quantity=1,
            avg_fill_price=100.0, order_intent_id=kwargs["order_intent_id"],
            order_log_path=kwargs["order_log_path"],
        )
        return _filled_result()

    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", fake_execute)
    paper_trading_runner._execute_confirmed_ibkr_paper_order("AAPL", "BUY", 1, 100.0)
    paper_trading_runner._execute_confirmed_ibkr_paper_order("AAPL", "BUY", 1, 100.0)
    lines = (tmp_path / "paper_orders.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    equity_lines = (tmp_path / "equity_history.csv").read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(equity_lines) == 2
    payload = json.loads((tmp_path / "paper_trade_pnls.json").read_text())
    assert payload["realized_trade_pnls"] == []
    drawdown = json.loads((tmp_path / "paper_drawdown.json").read_text(encoding="utf-8"))
    assert drawdown["equity_points"] == 1
    assert drawdown["maximum_drawdown"] == 0.0
