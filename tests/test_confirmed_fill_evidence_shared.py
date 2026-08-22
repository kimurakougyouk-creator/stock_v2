from types import SimpleNamespace

import pytest

import paper_trading_runner
from ai_asset_platform.execution.confirmed_fill_evidence import (
    confirmed_fill_from_broker_result,
)


def _result(**overrides):
    payload = dict(
        sent=True,
        reached_terminal=True,
        order_id=11,
        last_known_status=None,
        filled_quantity=1.0,
        avg_fill_price=100.0,
        executions=[],
        status="TERMINAL",
        timed_out=False,
        message="done",
        errors=[],
    )
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_explicit_filled_status_is_confirmed():
    result = _result(last_known_status="Filled", filled_quantity=1.0, avg_fill_price=101.5)
    assert confirmed_fill_from_broker_result(result, 1) == (1.0, 101.5)


def test_complete_execdetails_are_confirmed_without_open_order_status():
    result = _result(
        filled_quantity=0.0,
        avg_fill_price=None,
        executions=[
            {"order_id": 11, "exec_id": "A", "shares": 0.4, "price": 100.0},
            {"order_id": 11, "exec_id": "B", "shares": 0.6, "price": 102.0},
            {"order_id": 11, "exec_id": "B", "shares": 0.6, "price": 102.0},
        ],
    )
    quantity, price = confirmed_fill_from_broker_result(result, 1)
    assert quantity == pytest.approx(1.0)
    assert price == pytest.approx(101.2)


def test_partial_execdetails_remain_unconfirmed():
    result = _result(
        filled_quantity=0.0,
        avg_fill_price=None,
        executions=[
            {"order_id": 11, "exec_id": "A", "shares": 0.4, "price": 100.0},
        ],
    )
    assert confirmed_fill_from_broker_result(result, 1) is None


def test_absence_of_status_and_executions_is_not_fill_evidence():
    assert confirmed_fill_from_broker_result(_result(), 1) is None


def test_runner_accepts_complete_execdetails_using_same_shared_rule(monkeypatch):
    result = _result(
        filled_quantity=0.0,
        avg_fill_price=None,
        executions=[
            {"order_id": 11, "exec_id": "A", "shares": 1.0, "price": 123.45},
        ],
    )
    execution = SimpleNamespace(attempted=True, reason="ok", broker_result=result)

    monkeypatch.setattr(
        paper_trading_runner,
        "verified_paper_test_quantity_for_ticker",
        lambda ticker: 1,
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "execute_approved_signal_via_ibkr_paper",
        lambda **kwargs: execution,
    )
    monkeypatch.setattr(paper_trading_runner, "_sync_confirmed_fill_to_reporting", lambda: None)

    row = paper_trading_runner._execute_confirmed_ibkr_paper_order(
        "SPY", "BUY", 1, 120.0
    )
    assert row["status"] == "FILLED"
    assert row["shares"] == 1
    assert row["reference_price"] == pytest.approx(123.45)


def test_runner_still_rejects_partial_execdetails(monkeypatch):
    result = _result(
        filled_quantity=0.0,
        avg_fill_price=None,
        executions=[
            {"order_id": 11, "exec_id": "A", "shares": 0.5, "price": 123.45},
        ],
    )
    execution = SimpleNamespace(attempted=True, reason="ok", broker_result=result)
    monkeypatch.setattr(
        paper_trading_runner,
        "verified_paper_test_quantity_for_ticker",
        lambda ticker: 1,
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "execute_approved_signal_via_ibkr_paper",
        lambda **kwargs: execution,
    )

    with pytest.raises(RuntimeError, match="Filled"):
        paper_trading_runner._execute_confirmed_ibkr_paper_order(
            "SPY", "BUY", 1, 120.0
        )
