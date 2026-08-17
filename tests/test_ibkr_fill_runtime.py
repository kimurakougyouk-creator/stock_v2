from ai_asset_platform.brokers.ibkr_fill_runtime import IbkrFillRuntime
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide


def _order(quantity: int = 3) -> OrderRequest:
    return OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=quantity)


def test_runtime_converts_only_new_fill_and_persists(tmp_path):
    path = tmp_path / "ibkr_fill_state.json"
    fills = []
    runtime = IbkrFillRuntime(path, on_fill=fills.append)
    runtime.register_order(123, _order())

    first = runtime.process_order_status(123, "Submitted", 1, 2, 100.0)
    duplicate = runtime.process_order_status(123, "Submitted", 1, 2, 100.0)
    second = runtime.process_order_status(123, "Filled", 3, 0, 101.0)

    assert first is not None
    assert first.quantity == 1
    assert duplicate is None
    assert second is not None
    assert second.quantity == 2
    assert len(fills) == 2
    assert runtime.processed_filled(123) == 3
    assert path.exists()


def test_runtime_restores_processed_fill_after_restart(tmp_path):
    path = tmp_path / "ibkr_fill_state.json"

    first_runtime = IbkrFillRuntime(path)
    first_runtime.register_order(123, _order())
    first_runtime.process_order_status(123, "Submitted", 1, 2, 100.0)

    restarted = IbkrFillRuntime(path)
    restarted.register_order(123, _order())

    assert restarted.process_order_status(123, "Submitted", 1, 2, 100.0) is None
    new_fill = restarted.process_order_status(123, "Filled", 3, 0, 101.0)
    assert new_fill is not None
    assert new_fill.quantity == 2


def test_runtime_ignores_unknown_order(tmp_path):
    runtime = IbkrFillRuntime(tmp_path / "state.json")

    result = runtime.process_order_status(999, "Submitted", 1, 0, 100.0)

    assert result is None
