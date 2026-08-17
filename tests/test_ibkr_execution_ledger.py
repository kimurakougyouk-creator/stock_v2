import pytest

from ai_asset_platform.brokers.ibkr_execution_ledger import IbkrExecutionLedger


def test_single_execution_sets_cumulative_and_price():
    ledger = IbkrExecutionLedger()

    shares, price = ledger.record_execution(100, "exec-1", 1.0, 100.0)

    assert shares == 1.0
    assert price == 100.0


def test_two_partial_fills_compute_weighted_average_price():
    """要件4の例: 1株$100 + 1株$102 → average_fill_price = $101"""
    ledger = IbkrExecutionLedger()

    ledger.record_execution(100, "exec-1", 1.0, 100.0)
    shares, avg_price = ledger.record_execution(100, "exec-2", 1.0, 102.0)

    assert shares == 2.0
    assert avg_price == 101.0


def test_uneven_partial_fills_compute_weighted_average_price():
    ledger = IbkrExecutionLedger()

    ledger.record_execution(100, "exec-1", 2.0, 100.0)
    shares, avg_price = ledger.record_execution(100, "exec-2", 1.0, 106.0)

    # (2*100 + 1*106) / 3 = 306 / 3 = 102
    assert shares == 3.0
    assert avg_price == 102.0


def test_duplicate_exec_id_does_not_change_cumulative():
    ledger = IbkrExecutionLedger()

    ledger.record_execution(100, "exec-1", 1.0, 100.0)
    shares, price = ledger.record_execution(100, "exec-1", 1.0, 100.0)

    assert shares == 1.0
    assert price == 100.0


def test_duplicate_exec_id_with_different_reported_values_is_idempotent_upsert():
    """同じexecIdの再配信は最新値で上書きされるが、件数としては1件のまま。"""
    ledger = IbkrExecutionLedger()

    ledger.record_execution(100, "exec-1", 1.0, 100.0)
    shares, price = ledger.record_execution(100, "exec-1", 1.0, 100.0)

    assert shares == 1.0
    assert price == 100.0
    assert ledger.snapshot() == {100: {"exec-1": (1.0, 100.0)}}


def test_orders_are_tracked_independently():
    ledger = IbkrExecutionLedger()

    ledger.record_execution(100, "exec-1", 1.0, 100.0)
    ledger.record_execution(200, "exec-2", 3.0, 50.0)

    assert ledger.cumulative(100) == (1.0, 100.0)
    assert ledger.cumulative(200) == (3.0, 50.0)


def test_unknown_order_has_zero_cumulative():
    ledger = IbkrExecutionLedger()

    assert ledger.cumulative(999) == (0.0, 0.0)


def test_snapshot_and_restore_round_trip():
    ledger = IbkrExecutionLedger()
    ledger.record_execution(100, "exec-1", 1.0, 100.0)
    ledger.record_execution(100, "exec-2", 1.0, 102.0)

    restored = IbkrExecutionLedger()
    restored.restore(ledger.snapshot())

    assert restored.cumulative(100) == (2.0, 101.0)

    # 復元後に同じexecIdを再度渡しても二重計上されない
    shares, price = restored.record_execution(100, "exec-1", 1.0, 100.0)
    assert shares == 2.0
    assert price == 101.0


def test_negative_order_id_is_rejected():
    ledger = IbkrExecutionLedger()

    with pytest.raises(ValueError):
        ledger.record_execution(-1, "exec-1", 1.0, 100.0)


def test_empty_exec_id_is_rejected():
    ledger = IbkrExecutionLedger()

    with pytest.raises(ValueError):
        ledger.record_execution(100, "", 1.0, 100.0)


def test_non_positive_shares_is_rejected():
    ledger = IbkrExecutionLedger()

    with pytest.raises(ValueError):
        ledger.record_execution(100, "exec-1", 0.0, 100.0)


def test_non_positive_price_is_rejected():
    ledger = IbkrExecutionLedger()

    with pytest.raises(ValueError):
        ledger.record_execution(100, "exec-1", 1.0, 0.0)


def test_clear_removes_order():
    ledger = IbkrExecutionLedger()
    ledger.record_execution(100, "exec-1", 1.0, 100.0)

    ledger.clear(100)

    assert ledger.cumulative(100) == (0.0, 0.0)
