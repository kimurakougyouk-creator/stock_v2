import json

import pytest

from ai_asset_platform.brokers.ibkr_fill_pipeline import IbkrFillPipeline
from ai_asset_platform.brokers.ibkr_fill_state import IbkrFillStateStore
from ai_asset_platform.brokers.ibkr_fill_tracker import IbkrFillTracker
from ai_asset_platform.brokers.ibkr_order_events import (
    create_ibkr_order_status_event,
)
from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderSide,
    OrderType,
)


def _request(quantity: int = 3) -> OrderRequest:
    return OrderRequest(
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=quantity,
        order_type=OrderType.MARKET,
    )


def _event(
    filled: float,
    remaining: float,
    price: float = 200.0,
):
    return create_ibkr_order_status_event(
        order_id=100,
        status="Filled" if remaining == 0 else "Submitted",
        filled=filled,
        remaining=remaining,
        average_fill_price=price,
    )


def test_missing_state_file_returns_empty(tmp_path):
    store = IbkrFillStateStore(tmp_path / "ibkr_fill_state.json")

    assert store.load() == {}


def test_state_can_be_saved_and_loaded(tmp_path):
    store = IbkrFillStateStore(tmp_path / "ibkr_fill_state.json")

    store.save({100: 1.0, 200: 2.0})

    assert store.load() == {
        100: 1.0,
        200: 2.0,
    }


def test_tracker_snapshot_and_restore():
    tracker = IbkrFillTracker()

    tracker.restore({100: 2.0})

    assert tracker.processed_filled(100) == 2.0
    assert tracker.snapshot() == {100: 2.0}


def test_restart_does_not_duplicate_existing_fill(tmp_path):
    state_path = tmp_path / "ibkr_fill_state.json"
    store = IbkrFillStateStore(state_path)

    first_tracker = IbkrFillTracker()
    first_pipeline = IbkrFillPipeline(first_tracker)

    first_fill = first_pipeline.process(
        _request(3),
        _event(1, 2, 200.0),
    )

    assert first_fill is not None
    assert first_fill.quantity == 1

    store.save(first_tracker.snapshot())

    # Python再起動を想定して新しいインスタンスを作る。
    restarted_tracker = IbkrFillTracker()
    restarted_tracker.restore(store.load())
    restarted_pipeline = IbkrFillPipeline(restarted_tracker)

    duplicate = restarted_pipeline.process(
        _request(3),
        _event(1, 2, 200.0),
    )

    assert duplicate is None
    assert restarted_pipeline.processed_filled(100) == 1


def test_restart_processes_only_new_fill_delta(tmp_path):
    state_path = tmp_path / "ibkr_fill_state.json"
    store = IbkrFillStateStore(state_path)

    first_tracker = IbkrFillTracker()
    first_pipeline = IbkrFillPipeline(first_tracker)

    first_pipeline.process(
        _request(3),
        _event(1, 2, 200.0),
    )

    store.save(first_tracker.snapshot())

    restarted_tracker = IbkrFillTracker()
    restarted_tracker.restore(store.load())
    restarted_pipeline = IbkrFillPipeline(restarted_tracker)

    new_fill = restarted_pipeline.process(
        _request(3),
        _event(2, 1, 201.0),
    )

    assert new_fill is not None
    assert new_fill.quantity == 1
    assert new_fill.fill_price == 201.0
    assert restarted_pipeline.processed_filled(100) == 2


def test_corrupt_state_file_is_rejected(tmp_path):
    path = tmp_path / "ibkr_fill_state.json"
    path.write_text("{broken", encoding="utf-8")

    store = IbkrFillStateStore(path)

    with pytest.raises(ValueError):
        store.load()


def test_execution_ledger_can_be_saved_and_loaded(tmp_path):
    store = IbkrFillStateStore(tmp_path / "ibkr_fill_state.json")

    store.save(
        {100: 2.0},
        {100: {"exec-1": (1.0, 100.0), "exec-2": (1.0, 102.0)}},
    )

    assert store.load() == {100: 2.0}
    assert store.load_execution_ledger() == {
        100: {"exec-1": (1.0, 100.0), "exec-2": (1.0, 102.0)}
    }


def test_missing_execution_ledger_file_returns_empty(tmp_path):
    store = IbkrFillStateStore(tmp_path / "ibkr_fill_state.json")

    assert store.load_execution_ledger() == {}


def test_old_file_without_execution_ledger_key_loads_as_empty(tmp_path):
    """execution_ledgerキーを持たない旧バージョンのファイルでも安全に読める。"""
    path = tmp_path / "ibkr_fill_state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "processed_filled": {"100": 1.0},
            }
        ),
        encoding="utf-8",
    )

    store = IbkrFillStateStore(path)

    assert store.load() == {100: 1.0}
    assert store.load_execution_ledger() == {}


def test_save_without_execution_ledger_argument_defaults_to_empty(tmp_path):
    """execution_ledger引数を省略した既存呼び出しは壊れない(後方互換)。"""
    store = IbkrFillStateStore(tmp_path / "ibkr_fill_state.json")

    store.save({100: 1.0})

    assert store.load() == {100: 1.0}
    assert store.load_execution_ledger() == {}


def test_corrupt_execution_ledger_is_rejected(tmp_path):
    path = tmp_path / "ibkr_fill_state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "processed_filled": {"100": 1.0},
                "execution_ledger": {"100": "not-a-dict"},
            }
        ),
        encoding="utf-8",
    )

    store = IbkrFillStateStore(path)

    with pytest.raises(ValueError):
        store.load_execution_ledger()


def test_negative_saved_quantity_is_rejected(tmp_path):
    path = tmp_path / "ibkr_fill_state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "processed_filled": {
                    "100": -1,
                },
            }
        ),
        encoding="utf-8",
    )

    store = IbkrFillStateStore(path)

    with pytest.raises(ValueError):
        store.load()
