import pytest

from ai_asset_platform.account import Account
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter
from ai_asset_platform.execution.candidate_executor import execute_order_candidate
from ai_asset_platform.execution.order_candidate import OrderCandidate
from ai_asset_platform.execution.service import ExecutionService


def test_execute_buy_order_candidate():
    broker = SbiPaperAdapter()
    broker.connect()

    account = Account(initial_cash=1_000_000)
    service = ExecutionService(
        broker=broker,
        account=account,
    )

    candidate = OrderCandidate(
        symbol="7203.T",
        action="BUY",
        quantity=100,
    )

    fill = execute_order_candidate(
        candidate=candidate,
        execution_service=service,
        price=2500.0,
    )

    assert fill.symbol == "7203.T"
    assert fill.quantity == 100
    assert fill.fill_price == 2500.0
    assert account.cash == 750_000


def test_execute_order_candidate_rejects_invalid_action():
    broker = SbiPaperAdapter()
    broker.connect()

    account = Account(initial_cash=1_000_000)
    service = ExecutionService(
        broker=broker,
        account=account,
    )

    candidate = OrderCandidate(
        symbol="7203.T",
        action="HOLD",
        quantity=100,
    )

    with pytest.raises(ValueError, match="未対応の売買アクション"):
        execute_order_candidate(
            candidate=candidate,
            execution_service=service,
            price=2500.0,
        )
