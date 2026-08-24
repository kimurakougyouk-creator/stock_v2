import json
from types import SimpleNamespace

from ai_asset_platform.brokers.ibkr_reconciliation_evidence_audit import (
    audit_ibkr_reconciliation_evidence,
)
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
)


def _position(symbol, quantity, *, average_cost=0.0, market_price=0.0):
    return SimpleNamespace(
        symbol=symbol,
        sec_type="STK",
        currency="USD",
        exchange="NASDAQ" if symbol == "AAPL" else "ARCA",
        quantity=quantity,
        market_price=market_price,
        market_value=0.0,
        average_cost=average_cost,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
    )


def _account(*positions, ready=True):
    return SimpleNamespace(
        connected=ready,
        endpoint_port=4002 if ready else None,
        account_id="DU123" if ready else None,
        account_ready=ready,
        base_currency="JPY" if ready else None,
        net_liquidation=1_000_000.0 if ready else None,
        available_funds=900_000.0 if ready else None,
        gross_position_value=100_000.0 if ready else None,
        total_cash_value=900_000.0 if ready else None,
        positions=tuple(positions),
        order_sent=False,
        errors=(),
        ready=ready,
    )


def _execution(symbol, side, qty, price, order_id, exec_id):
    return IbkrExecutionEvidence(
        exec_id=exec_id,
        order_id=order_id,
        perm_id=123,
        symbol=symbol,
        sec_type="STK",
        currency="USD",
        exchange="NASDAQ" if symbol == "AAPL" else "ARCA",
        side=side,
        quantity=qty,
        price=price,
        time="20260824 10:00:00 Asia/Tokyo",
        account="DU123",
    )


def _snapshot(*executions, ready=True):
    return IbkrPaperExecutionSnapshot(
        connected=ready,
        endpoint_port=4002 if ready else None,
        executions=tuple(executions),
        order_sent=False,
        errors=(),
    )


def _write(tmp_path, rows):
    path = tmp_path / "paper_orders.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_audit_detects_aapl_broker_local_quantity_gap_without_mutation(tmp_path):
    path = _write(tmp_path, [{
        "created_at": "2026-08-21T07:22:13",
        "mode": "IBKR_PAPER",
        "ticker": "AAPL",
        "side": "BUY",
        "shares": 1,
        "reference_price": 312.2,
        "status": "FILLED",
        "order_intent_id": "signal-runner:AAPL:BUY:1:0.00000000",
    }])
    before = path.read_text(encoding="utf-8")
    result = audit_ibkr_reconciliation_evidence(
        order_log_path=path,
        account=_account(_position("AAPL", 3, average_cost=311.5, market_price=312.0)),
        execution_snapshot=_snapshot(),
    )
    after = path.read_text(encoding="utf-8")
    aapl = next(item for item in result.symbols if item.ticker == "AAPL")
    assert aapl.broker_quantity == 3
    assert aapl.local_confirmed_quantity == 1
    assert aapl.quantity_gap == 2
    assert result.next_action == "REVIEW_AAPL_PAPER_POSITION_RESET_BEFORE_NEW_EXPOSURE"
    assert result.order_sent is False
    assert result.ledger_changed is False
    assert before == after


def test_audit_matches_spy_blocker_by_broker_order_id(tmp_path):
    path = _write(tmp_path, [{
        "created_at": "2026-08-23T23:00:00+09:00",
        "mode": "IBKR_PAPER",
        "ticker": "SPY",
        "side": "SELL",
        "shares": 1,
        "reference_price": 765.0,
        "currency": "USD",
        "status": "FILLED",
        "order_intent_id": "broker-recovery:abc",
        "broker_order_id": 77,
    }])
    execution = _execution("SPY", "SELL", 1.0, 765.0, 77, "abc")
    result = audit_ibkr_reconciliation_evidence(
        order_log_path=path,
        account=_account(),
        execution_snapshot=_snapshot(execution),
    )
    assert len(result.blockers) == 1
    blocker = result.blockers[0]
    assert blocker.reason == "missing-historical-fx"
    assert blocker.broker_order_id == 77
    assert blocker.order_id_execution_matches == (execution,)
    assert result.next_action == "RECOVER_UNIQUE_BROKER_EXECUTION_EVIDENCE"


def test_exec_id_identity_is_matched(tmp_path):
    path = _write(tmp_path, [{
        "created_at": "2026-08-23T23:00:00+09:00",
        "mode": "IBKR_PAPER",
        "ticker": "SPY",
        "side": "BUY",
        "shares": 1,
        "reference_price": 764.0,
        "currency": "USD",
        "status": "FILLED",
        "order_intent_id": "known",
        "broker_exec_ids": ["e-1"],
    }])
    execution = _execution("SPY", "BUY", 1.0, 764.0, 55, "e-1")
    result = audit_ibkr_reconciliation_evidence(
        order_log_path=path,
        account=_account(_position("SPY", 1, average_cost=764.0, market_price=765.0)),
        execution_snapshot=_snapshot(execution),
    )
    assert result.blockers[0].exec_id_execution_matches == (execution,)


def test_clean_ledger_and_flat_broker_is_clean(tmp_path):
    path = _write(tmp_path, [])
    result = audit_ibkr_reconciliation_evidence(
        order_log_path=path,
        account=_account(),
        execution_snapshot=_snapshot(),
    )
    assert result.blockers == ()
    assert result.next_action == "RECONCILIATION_EVIDENCE_IS_CLEAN"


def test_not_ready_account_fails_closed(tmp_path):
    path = _write(tmp_path, [])
    result = audit_ibkr_reconciliation_evidence(
        order_log_path=path,
        account=_account(ready=False),
        execution_snapshot=_snapshot(),
    )
    assert result.next_action == "BLOCKED_BROKER_ACCOUNT_SNAPSHOT_NOT_READY"


def test_not_ready_execution_snapshot_fails_closed(tmp_path):
    path = _write(tmp_path, [])
    result = audit_ibkr_reconciliation_evidence(
        order_log_path=path,
        account=_account(),
        execution_snapshot=_snapshot(ready=False),
    )
    assert result.next_action == "BLOCKED_EXECUTION_SNAPSHOT_NOT_READY"
