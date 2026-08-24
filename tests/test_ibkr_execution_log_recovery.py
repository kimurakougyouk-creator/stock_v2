from pathlib import Path

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrBrokerPosition,
    IbkrPaperAccountSnapshot,
)
from ai_asset_platform.execution.ibkr_execution_reconcile import ReconciliationResult
import ai_asset_platform.execution.ibkr_execution_log_recovery as recovery


def _account(*, qty: float = 1.0, average_cost: float = 765.45):
    return IbkrPaperAccountSnapshot(
        connected=True,
        endpoint_port=4002,
        account_id="DU_TEST",
        account_ready=True,
        base_currency="JPY",
        net_liquidation=1_000_000.0,
        available_funds=900_000.0,
        gross_position_value=100_000.0,
        total_cash_value=900_000.0,
        positions=(
            IbkrBrokerPosition(
                symbol="SPY",
                sec_type="STK",
                currency="USD",
                exchange="ARCA",
                quantity=qty,
                market_price=760.0,
                market_value=760.0 * qty,
                average_cost=average_cost,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            ),
        ),
        order_sent=False,
        errors=(),
    )


def _write_execution_log(path: Path, *, price: float = 765.45):
    path.write_text(
        "===== IBKR PAPER EXECUTION SNAPSHOT =====\n"
        f"EXECUTION 1: symbol=SPY side=BUY qty=1 price={price} currency=USD "
        "exchange=BYX order_id=3 perm_id=1233595586 "
        "exec_id=00012ec5.6ab91096.01.01 "
        "time=20260821 16:33:06 US/Eastern\n",
        encoding="utf-8",
    )


def test_parse_execution_log_recovers_exact_broker_identity(tmp_path):
    path = tmp_path / "snapshot.log"
    _write_execution_log(path)
    parsed = recovery._parse_execution_log(path)
    assert len(parsed) == 1
    item = parsed[0]
    assert item.symbol == "SPY"
    assert item.side == "BUY"
    assert item.quantity == 1.0
    assert item.price == 765.45
    assert item.currency == "USD"
    assert item.order_id == 3
    assert item.exec_id == "00012ec5.6ab91096.01.01"


def test_recovery_requires_broker_and_log_agreement(monkeypatch, tmp_path):
    execution_log = tmp_path / "snapshot.log"
    order_log = tmp_path / "orders.jsonl"
    _write_execution_log(execution_log)
    monkeypatch.setattr(recovery.order_manager, "load_accounting_orders", lambda: [])
    observed = {}

    def fake_reconcile(snapshot, *, order_log_path):
        observed["snapshot"] = snapshot
        observed["path"] = order_log_path
        return ReconciliationResult(1, 0, ())

    monkeypatch.setattr(recovery, "reconcile_execution_snapshot_to_ledger", fake_reconcile)
    result = recovery.recover_spy_execution_from_log(
        execution_log_path=execution_log,
        order_log_path=order_log,
        account=_account(),
    )
    assert result.recovered is True
    assert observed["path"] == order_log
    assert observed["snapshot"].executions[0].exec_id == "00012ec5.6ab91096.01.01"
    assert observed["snapshot"].order_sent is False


def test_recovery_accepts_small_broker_average_cost_fee_delta(monkeypatch, tmp_path):
    execution_log = tmp_path / "snapshot.log"
    order_log = tmp_path / "orders.jsonl"
    _write_execution_log(execution_log, price=765.45)
    monkeypatch.setattr(recovery.order_manager, "load_accounting_orders", lambda: [])

    called = {"value": False}

    def fake_reconcile(snapshot, *, order_log_path):
        called["value"] = True
        return ReconciliationResult(1, 0, ())

    monkeypatch.setattr(recovery, "reconcile_execution_snapshot_to_ledger", fake_reconcile)
    result = recovery.recover_spy_execution_from_log(
        execution_log_path=execution_log,
        order_log_path=order_log,
        account=_account(average_cost=766.10),
    )
    assert result.recovered is True
    assert called["value"] is True


def test_recovery_fails_closed_when_average_cost_disagrees(monkeypatch, tmp_path):
    execution_log = tmp_path / "snapshot.log"
    _write_execution_log(execution_log, price=700.0)
    monkeypatch.setattr(recovery.order_manager, "load_accounting_orders", lambda: [])
    called = {"value": False}

    def forbidden(*args, **kwargs):
        called["value"] = True
        raise AssertionError("reconciliation must not run")

    monkeypatch.setattr(recovery, "reconcile_execution_snapshot_to_ledger", forbidden)
    result = recovery.recover_spy_execution_from_log(
        execution_log_path=execution_log,
        order_log_path=tmp_path / "orders.jsonl",
        account=_account(average_cost=765.45),
    )
    assert result.recovered is False
    assert "average cost" in result.reason
    assert called["value"] is False


def test_recovery_does_nothing_when_local_spy_is_already_one(monkeypatch, tmp_path):
    execution_log = tmp_path / "snapshot.log"
    _write_execution_log(execution_log)
    monkeypatch.setattr(
        recovery.order_manager,
        "load_accounting_orders",
        lambda: [
            {
                "status": "FILLED",
                "ticker": "SPY",
                "side": "BUY",
                "shares": 1,
                "order_intent_id": "existing",
            }
        ],
    )
    result = recovery.recover_spy_execution_from_log(
        execution_log_path=execution_log,
        order_log_path=tmp_path / "orders.jsonl",
        account=_account(),
    )
    assert result.recovered is False
    assert "already reconciled" in result.reason
