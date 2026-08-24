from decimal import Decimal

from ai_asset_platform.accounting.futures_postfill_audit import evaluate_futures_postfill_audit
from ai_asset_platform.brokers.ibkr_execution_snapshot import (
    IbkrExecutionEvidence,
    IbkrPaperExecutionSnapshot,
)


def _row(side: str, exec_id: str, price: float):
    return IbkrExecutionEvidence(
        exec_id=exec_id,
        order_id=1 if side == "BUY" else 2,
        perm_id=11 if side == "BUY" else 12,
        symbol="ES",
        sec_type="FUT",
        currency="USD",
        exchange="CME",
        side=side,
        quantity=1.0,
        price=price,
        time="20260824 10:00:00 US/Central",
        account="DU123",
        con_id=649180671,
        local_symbol="ESU6",
        expiry="20260918",
        multiplier="50",
    )


def _snapshot(*rows):
    return IbkrPaperExecutionSnapshot(True, 4002, tuple(rows), False, ())


def test_verified_real_observed_prices_produce_expected_accounting():
    first = _snapshot(_row("BUY", "buy.exec", 7668.25), _row("SELL", "sell.exec", 7667.75))
    second = _snapshot(_row("BUY", "buy.exec", 7668.25), _row("SELL", "sell.exec", 7667.75))
    result = evaluate_futures_postfill_audit(first, second, broker_flat=True)
    assert result.ready is True
    assert result.realized_pnl_usd == Decimal("-25.00")
    assert result.unrealized_pnl_usd == Decimal("0")
    assert result.ending_equity_delta_usd == Decimal("-25.00")
    assert result.max_drawdown_usd == Decimal("25.00")
    assert result.ending_contracts == 0
    assert result.restart_recovery_verified is True
    assert result.broker_flat_verified is True
    assert result.real_order_sent is False
    assert result.live_order_sent is False


def test_missing_execution_blocks_audit():
    one = _snapshot(_row("BUY", "buy.exec", 7668.25))
    result = evaluate_futures_postfill_audit(one, one, broker_flat=True)
    assert result.ready is False
    assert "exactly two" in result.reason


def test_restart_identity_change_blocks_audit():
    first = _snapshot(_row("BUY", "buy.exec", 7668.25), _row("SELL", "sell.exec", 7667.75))
    second = _snapshot(_row("BUY", "buy.exec", 7668.25), _row("SELL", "different.exec", 7667.75))
    result = evaluate_futures_postfill_audit(first, second, broker_flat=True)
    assert result.ready is False
    assert result.restart_recovery_verified is False


def test_nonflat_broker_blocks_audit():
    snap = _snapshot(_row("BUY", "buy.exec", 7668.25), _row("SELL", "sell.exec", 7667.75))
    result = evaluate_futures_postfill_audit(snap, snap, broker_flat=False)
    assert result.ready is False
    assert result.broker_flat_verified is False
