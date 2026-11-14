from types import SimpleNamespace

import ai_asset_platform.execution.broker_open_order_guard as module


def _snapshot(*, ready=True, orders=()):
    return SimpleNamespace(ready=ready, orders=orders)


def _order(order_id, symbol):
    return SimpleNamespace(order_id=order_id, symbol=symbol)


def test_guard_blocks_when_an_open_order_exists_for_the_same_symbol():
    snapshot = _snapshot(orders=(_order(7, "AAPL"),))
    result = module.evaluate_open_order_guard(ticker="AAPL", symbol="AAPL", snapshot=snapshot)
    assert result.allowed is False
    assert result.matching_order_ids == (7,)
    assert "already exists" in result.reason


def test_guard_allows_when_no_open_order_matches_the_symbol():
    snapshot = _snapshot(orders=(_order(7, "SPY"),))
    result = module.evaluate_open_order_guard(ticker="AAPL", symbol="AAPL", snapshot=snapshot)
    assert result.allowed is True
    assert result.matching_order_ids == ()


def test_guard_ignores_client_id_and_catches_orders_from_other_sessions():
    """reqAllOpenOrders (used by the underlying snapshot) returns orders
    placed under any client id, not only this session's own -- this is the
    exact gap being closed: a resting order from an earlier, separate
    connection must still be caught here."""
    snapshot = _snapshot(orders=(_order(99, "9432"),))
    result = module.evaluate_open_order_guard(ticker="9432.T", symbol="9432", snapshot=snapshot)
    assert result.allowed is False


def test_guard_fails_closed_when_snapshot_is_not_ready():
    snapshot = _snapshot(ready=False, orders=())
    result = module.evaluate_open_order_guard(ticker="AAPL", symbol="AAPL", snapshot=snapshot)
    assert result.allowed is False
    assert "not ready" in result.reason


def test_guard_rejects_empty_ticker_or_symbol():
    snapshot = _snapshot(orders=())
    result = module.evaluate_open_order_guard(ticker="", symbol="AAPL", snapshot=snapshot)
    assert result.allowed is False
    assert "invalid order identity" in result.reason


def test_guard_calls_broker_when_no_snapshot_is_supplied(monkeypatch):
    calls = []
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_all_open_orders",
        lambda **kwargs: calls.append(kwargs) or _snapshot(orders=()),
    )
    result = module.evaluate_open_order_guard(ticker="AAPL", symbol="AAPL")
    assert calls == [{"expected_account_id": None}]
    assert result.allowed is True


def test_guard_forwards_expected_account_id_to_the_broker_probe(monkeypatch):
    """Codex finding on PR #375: the open-order probe independently tries
    Gateway then TWS and must be bound to the same account the order-placing
    connection was verified against, or a Gateway/TWS account mismatch could
    return an empty snapshot from the wrong account and wrongly allow a
    duplicate order through."""
    calls = []
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_all_open_orders",
        lambda **kwargs: calls.append(kwargs) or _snapshot(orders=()),
    )
    module.evaluate_open_order_guard(
        ticker="AAPL", symbol="AAPL", expected_account_id="DU1234567"
    )
    assert calls == [{"expected_account_id": "DU1234567"}]
