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


# --- execDetails経路 ---


def test_process_execution_produces_fill_without_order_status(tmp_path):
    """orderStatusを一度も呼ばず、execDetailsだけでFillResultが生成されること。"""
    runtime = IbkrFillRuntime(tmp_path / "state.json")
    runtime.register_order(123, _order(1))

    result = runtime.process_execution(123, "exec-1", 1.0, 100.0)

    assert result is not None
    assert result.quantity == 1
    assert result.fill_price == 100.0
    assert runtime.processed_filled(123) == 1


def test_process_execution_two_partial_fills_use_weighted_average_price(tmp_path):
    """要件4の例: 1株$100 + 1株$102 → average_fill_price = $101。
    単一execDetailsのpriceをそのまま使わないことを検証する。
    """
    runtime = IbkrFillRuntime(tmp_path / "state.json")
    runtime.register_order(123, _order(2))

    first = runtime.process_execution(123, "exec-1", 1.0, 100.0)
    second = runtime.process_execution(123, "exec-2", 1.0, 102.0)

    assert first is not None
    assert first.fill_price == 100.0
    assert second is not None
    # 2件目のFillResultは「差分」の1株分だが、価格は累積の加重平均($101)。
    assert second.fill_price == 101.0
    assert runtime.processed_filled(123) == 2


def test_process_execution_duplicate_exec_id_does_not_double_count(tmp_path):
    fills = []
    runtime = IbkrFillRuntime(tmp_path / "state.json", on_fill=fills.append)
    runtime.register_order(123, _order(1))

    first = runtime.process_execution(123, "exec-1", 1.0, 100.0)
    duplicate = runtime.process_execution(123, "exec-1", 1.0, 100.0)

    assert first is not None
    assert duplicate is None
    assert len(fills) == 1
    assert runtime.processed_filled(123) == 1


def test_order_status_and_exec_details_for_same_fill_do_not_double_count(tmp_path):
    """orderStatusとexecDetailsが同じ約定を報告しても、FillResultは1回だけ。"""
    fills = []
    runtime = IbkrFillRuntime(tmp_path / "state.json", on_fill=fills.append)
    runtime.register_order(123, _order(1))

    from_order_status = runtime.process_order_status(123, "Filled", 1, 0, 100.0)
    from_exec_details = runtime.process_execution(123, "exec-1", 1.0, 100.0)

    assert from_order_status is not None
    assert from_exec_details is None
    assert len(fills) == 1
    assert runtime.processed_filled(123) == 1


def test_exec_details_arriving_before_order_status_do_not_double_count(tmp_path):
    """到着順序が逆(execDetails→orderStatus)でも二重計上しない。"""
    fills = []
    runtime = IbkrFillRuntime(tmp_path / "state.json", on_fill=fills.append)
    runtime.register_order(123, _order(1))

    from_exec_details = runtime.process_execution(123, "exec-1", 1.0, 100.0)
    from_order_status = runtime.process_order_status(123, "Filled", 1, 0, 100.0)

    assert from_exec_details is not None
    assert from_order_status is None
    assert len(fills) == 1


def test_delayed_order_status_after_exec_details_does_not_raise(tmp_path):
    """execDetailsが先に累積を進めた後、遅延したorderStatusが
    それより低い累積値を報告しても例外にならず、安全に無視されること。
    """
    runtime = IbkrFillRuntime(tmp_path / "state.json")
    runtime.register_order(123, _order(2))

    runtime.process_execution(123, "exec-1", 1.0, 100.0)
    runtime.process_execution(123, "exec-2", 1.0, 102.0)
    assert runtime.processed_filled(123) == 2

    # 遅延して届いたorderStatus(filled=1)は既知の2を下回るため無視される。
    stale = runtime.process_order_status(123, "Submitted", 1, 1, 100.0)

    assert stale is None
    assert runtime.processed_filled(123) == 2


def test_runtime_restores_execution_ledger_after_restart(tmp_path):
    path = tmp_path / "state.json"

    first_runtime = IbkrFillRuntime(path)
    first_runtime.register_order(123, _order(2))
    first_runtime.process_execution(123, "exec-1", 1.0, 100.0)

    restarted = IbkrFillRuntime(path)
    restarted.register_order(123, _order(2))

    # 復元後、同じexecIdの再配信は二重計上されない。
    duplicate = restarted.process_execution(123, "exec-1", 1.0, 100.0)
    assert duplicate is None

    # 新しいexecIdは正しく差分だけ計上される。
    new_fill = restarted.process_execution(123, "exec-2", 1.0, 102.0)
    assert new_fill is not None
    assert new_fill.quantity == 1
    assert new_fill.fill_price == 101.0
    assert restarted.processed_filled(123) == 2
