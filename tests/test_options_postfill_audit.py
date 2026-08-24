from decimal import Decimal

from ai_asset_platform.accounting.options_postfill_audit import evaluate_option_postfill_audit
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
)


def _row(*, exec_id, order_id, side, price, quantity=1.0, con_id=900369377):
    return IbkrExecutionEvidence(
        exec_id=exec_id,
        order_id=order_id,
        perm_id=order_id + 1000,
        symbol="SPY",
        sec_type="OPT",
        currency="USD",
        exchange="SMART",
        side=side,
        quantity=quantity,
        price=price,
        time="20260825 09:31:00 US/Eastern",
        account="DU123",
        con_id=con_id,
        local_symbol="SPY   260828C00765000",
        expiry="20260828",
        multiplier="100",
    )


def _snapshot(rows):
    return IbkrPaperExecutionSnapshot(
        connected=True,
        endpoint_port=4002,
        executions=tuple(rows),
        order_sent=False,
        errors=(),
    )


def test_latest_consecutive_pair_is_accounted_with_multiplier_and_restart():
    historical = [
        _row(exec_id="OLD-B", order_id=1, side="BUY", price=4.00),
        _row(exec_id="OLD-S", order_id=2, side="SELL", price=4.10),
    ]
    latest = [
        _row(exec_id="NEW-B", order_id=7, side="BUY", price=5.20),
        _row(exec_id="NEW-S", order_id=8, side="SELL", price=5.05),
    ]
    first = _snapshot(historical + latest)
    second = _snapshot(historical + latest)
    result = evaluate_option_postfill_audit(first, second, broker_flat=True)
    assert result.ready is True
    assert result.selected_buy_order_id == 7
    assert result.selected_sell_order_id == 8
    assert result.selected_exec_ids == ("NEW-B", "NEW-S")
    assert result.realized_pnl_usd == Decimal("-15.000")
    assert result.unrealized_pnl_usd == Decimal("0")
    assert result.max_drawdown_usd == Decimal("15.000")
    assert result.restart_recovery_verified is True
    assert result.broker_flat_verified is True


def test_exact_historical_pair_from_real_paper_run_recovers():
    rows = [
        _row(
            exec_id="00020057.6a8c86b2.01.01",
            order_id=1,
            side="BUY",
            price=4.08,
        ),
        _row(
            exec_id="00020057.6a8c86b3.01.01",
            order_id=2,
            side="SELL",
            price=4.07,
        ),
    ]
    result = evaluate_option_postfill_audit(_snapshot(rows), _snapshot(rows), broker_flat=True)
    assert result.ready is True
    assert result.selected_buy_order_id == 1
    assert result.selected_sell_order_id == 2
    assert result.selected_exec_ids == (
        "00020057.6a8c86b2.01.01",
        "00020057.6a8c86b3.01.01",
    )
    assert result.realized_pnl_usd == Decimal("-1.00")
    assert result.unrealized_pnl_usd == Decimal("0")
    assert result.max_drawdown_usd == Decimal("1.00")
    assert result.restart_recovery_verified is True
    assert result.broker_flat_verified is True


def test_split_execution_one_contract_is_aggregated():
    rows = [
        _row(exec_id="B1", order_id=9, side="BUY", price=5.00, quantity=0.4),
        _row(exec_id="B2", order_id=9, side="BUY", price=5.20, quantity=0.6),
        _row(exec_id="S1", order_id=10, side="SELL", price=5.30, quantity=1.0),
    ]
    result = evaluate_option_postfill_audit(_snapshot(rows), _snapshot(rows), broker_flat=True)
    assert result.ready is True
    assert result.selected_exec_ids == ("B1", "B2", "S1")
    assert result.realized_pnl_usd == Decimal("18.000")


def test_nonconsecutive_orders_are_not_trusted():
    rows = [
        _row(exec_id="B", order_id=11, side="BUY", price=5.0),
        _row(exec_id="S", order_id=13, side="SELL", price=5.1),
    ]
    result = evaluate_option_postfill_audit(_snapshot(rows), _snapshot(rows), broker_flat=True)
    assert result.ready is False
    assert "no exact consecutive" in result.reason


def test_contract_drift_is_ignored_and_cannot_form_pair():
    rows = [
        _row(exec_id="B", order_id=11, side="BUY", price=5.0),
        _row(exec_id="S", order_id=12, side="SELL", price=5.1, con_id=900369378),
    ]
    result = evaluate_option_postfill_audit(_snapshot(rows), _snapshot(rows), broker_flat=True)
    assert result.ready is False


def test_restart_snapshot_must_recover_same_exec_ids():
    first_rows = [
        _row(exec_id="B", order_id=21, side="BUY", price=5.0),
        _row(exec_id="S", order_id=22, side="SELL", price=5.1),
    ]
    second_rows = [first_rows[0]]
    result = evaluate_option_postfill_audit(
        _snapshot(first_rows), _snapshot(second_rows), broker_flat=True
    )
    assert result.ready is False
    assert result.restart_recovery_verified is False


def test_broker_must_be_flat():
    rows = [
        _row(exec_id="B", order_id=31, side="BUY", price=5.0),
        _row(exec_id="S", order_id=32, side="SELL", price=5.1),
    ]
    result = evaluate_option_postfill_audit(_snapshot(rows), _snapshot(rows), broker_flat=False)
    assert result.ready is False
    assert result.broker_flat_verified is False
