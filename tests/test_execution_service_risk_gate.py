from unittest.mock import Mock

import pytest

from ai_asset_platform.account import Account
from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.execution.service import ExecutionService, RiskGateResult


def _order() -> OrderRequest:
    return OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)


def test_risk_gate_blocks_before_ibkr_send() -> None:
    broker = Mock(spec=IbkrBrokerAdapter)
    broker.is_connected.return_value = True
    broker.place_order_and_await_fill = Mock()
    broker.__class__ = IbkrBrokerAdapter
    account = Account(initial_cash=1_000_000)
    gate = Mock(return_value=RiskGateResult(False, "daily loss limit"))
    service = ExecutionService(broker=broker, account=account, risk_gate=gate)

    with pytest.raises(RuntimeError, match="daily loss limit"):
        service.execute_ibkr_paper_order(_order(), order_intent_id="risk-block")

    gate.assert_called_once()
    broker.place_order_and_await_fill.assert_not_called()


def test_invalid_risk_gate_result_blocks_before_ibkr_send() -> None:
    broker = Mock(spec=IbkrBrokerAdapter)
    broker.is_connected.return_value = True
    broker.place_order_and_await_fill = Mock()
    broker.__class__ = IbkrBrokerAdapter
    service = ExecutionService(
        broker=broker,
        account=Account(initial_cash=1_000_000),
        risk_gate=lambda order: True,
    )

    with pytest.raises(TypeError, match="RiskGateResult"):
        service.execute_ibkr_paper_order(_order(), order_intent_id="invalid-gate")

    broker.place_order_and_await_fill.assert_not_called()


def test_existing_sync_execution_remains_compatible_without_risk_gate() -> None:
    from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter

    broker = SbiPaperAdapter()
    account = Account(initial_cash=1_000_000)
    service = ExecutionService(broker=broker, account=account)
    assert broker.connect() is True

    fill = service.execute_market_order(
        symbol="7203.T",
        side=OrderSide.BUY,
        quantity=1,
        price=2500.0,
    )

    assert fill.quantity == 1
    assert account.cash == 997_500.0
