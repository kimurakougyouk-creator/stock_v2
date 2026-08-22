import json
from datetime import date, datetime

import order_manager


def _write(path, rows):
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _ibkr(side, shares, price, status, *, ticker="AAPL", created_at=None):
    return {
        "created_at": created_at or datetime.now().isoformat(timespec="seconds"),
        "mode": "IBKR_PAPER",
        "ticker": ticker,
        "side": side,
        "shares": shares,
        "reference_price": price,
        "status": status,
    }


def test_unconfirmed_ibkr_rows_do_not_change_cash_or_positions(tmp_path, monkeypatch):
    path = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", path)
    _write(path, [
        _ibkr("BUY", 1, 100, "READY"),
        _ibkr("BUY", 1, 100, "SENT"),
        _ibkr("BUY", 1, 100, "REJECTED"),
        _ibkr("BUY", 1, 100, "SUBMITTED"),
    ])

    assert order_manager.load_accounting_orders() == []
    assert order_manager.calculate_available_cash(1000) == 1000
    assert order_manager.get_open_positions() == {}
    assert order_manager.calculate_realized_trade_pnls() == []


def test_only_filled_ibkr_rows_change_accounting_state(tmp_path, monkeypatch):
    path = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", path)
    _write(path, [
        _ibkr("BUY", 2, 100, "FILLED"),
        _ibkr("SELL", 1, 120, "FILLED"),
        _ibkr("SELL", 1, 999, "SENT"),
    ])

    assert order_manager.calculate_available_cash(1000) == 920
    assert order_manager.get_open_positions() == {"AAPL": 1}
    assert order_manager.calculate_realized_trade_pnls() == [20.0]
    assert order_manager.calculate_unrealized_pnl({"AAPL": 120}) == {"AAPL": 40.0}


def test_unconfirmed_ibkr_sell_does_not_trigger_realized_loss_or_cooldown(tmp_path, monkeypatch):
    path = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", path)
    now = datetime.now().isoformat(timespec="seconds")
    _write(path, [
        _ibkr("BUY", 1, 100, "FILLED", created_at=now),
        _ibkr("SELL", 1, 50, "SENT", created_at=now),
    ])

    assert order_manager.calculate_daily_realized_pnl(date.today()) == 0.0
    assert order_manager.calculate_consecutive_losses() == 0
    assert order_manager.calculate_repurchase_cooldown_remaining_minutes(
        "AAPL", 60, current_time=datetime.now()
    ) == 0


def test_legacy_paper_recorded_orders_keep_existing_behavior(tmp_path, monkeypatch):
    path = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", path)
    _write(path, [
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "PAPER",
            "ticker": "7203.T",
            "side": "BUY",
            "shares": 100,
            "reference_price": 2500.0,
            "status": "RECORDED",
        }
    ])

    assert order_manager.calculate_available_cash(1_000_000) == 750_000
    assert order_manager.get_open_positions() == {"7203.T": 100}


def test_legacy_statusless_rows_are_kept_but_known_unconfirmed_statusless_mode_is_blocked(tmp_path, monkeypatch):
    path = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", path)
    legacy = {
        "ticker": "7203.T",
        "side": "BUY",
        "shares": 100,
        "reference_price": 2500.0,
    }
    blocked = dict(legacy, status="READY")
    _write(path, [legacy, blocked])

    accounting = order_manager.load_accounting_orders()
    assert accounting == [legacy]


def test_explicit_unknown_broker_mode_fails_closed_without_filled_evidence(tmp_path, monkeypatch):
    path = tmp_path / "paper_orders.jsonl"
    monkeypatch.setattr(order_manager, "ORDER_LOG_PATH", path)
    _write(path, [
        {"mode": "OTHER_BROKER_PAPER", "status": "SENT", "ticker": "X", "side": "BUY", "shares": 1, "reference_price": 10},
        {"mode": "OTHER_BROKER_PAPER", "status": "FILLED", "ticker": "X", "side": "BUY", "shares": 1, "reference_price": 10},
    ])

    assert len(order_manager.load_accounting_orders()) == 1
    assert order_manager.get_open_positions() == {"X": 1}
