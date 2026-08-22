from types import SimpleNamespace

from ai_asset_platform.execution.ibkr_signal_runtime import (
    _confirmed_fill_from_broker_result,
)


def _result(**overrides):
    values = {
        "sent": True,
        "reached_terminal": True,
        "order_id": 7,
        "last_known_status": None,
        "filled_quantity": 1.0,
        "avg_fill_price": 100.0,
        "executions": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_normal_filled_order_status_is_confirmed():
    result = _result(last_known_status="Filled")
    assert _confirmed_fill_from_broker_result(result, 1) == (1.0, 100.0)


def test_full_execdetails_confirm_fill_even_if_open_order_row_disappeared():
    result = _result(
        last_known_status=None,
        executions=[
            {"order_id": 7, "exec_id": "a", "shares": 0.4, "price": 100.0},
            {"order_id": 7, "exec_id": "b", "shares": 0.6, "price": 110.0},
        ],
    )
    quantity, price = _confirmed_fill_from_broker_result(result, 1)
    assert quantity == 1.0
    assert price == 106.0


def test_duplicate_exec_id_cannot_double_count_to_full_fill():
    result = _result(
        filled_quantity=0.5,
        avg_fill_price=100.0,
        executions=[
            {"order_id": 7, "exec_id": "same", "shares": 0.5, "price": 100.0},
            {"order_id": 7, "exec_id": "same", "shares": 0.5, "price": 100.0},
        ],
    )
    assert _confirmed_fill_from_broker_result(result, 1) is None


def test_partial_execdetails_never_confirm_full_fill():
    result = _result(
        filled_quantity=0.5,
        executions=[
            {"order_id": 7, "exec_id": "a", "shares": 0.5, "price": 100.0},
        ],
    )
    assert _confirmed_fill_from_broker_result(result, 1) is None


def test_missing_open_order_without_execution_evidence_is_not_filled():
    result = _result(last_known_status=None, executions=[])
    assert _confirmed_fill_from_broker_result(result, 1) is None


def test_not_sent_or_nonterminal_result_never_confirms():
    assert _confirmed_fill_from_broker_result(_result(sent=False), 1) is None
    assert _confirmed_fill_from_broker_result(_result(reached_terminal=False), 1) is None


def test_other_order_execution_is_ignored():
    result = _result(
        executions=[
            {"order_id": 8, "exec_id": "foreign", "shares": 5, "price": 100.0},
        ]
    )
    assert _confirmed_fill_from_broker_result(result, 1) is None
