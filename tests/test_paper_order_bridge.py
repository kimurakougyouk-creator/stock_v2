import pytest

from ai_asset_platform.account import Account
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter
from ai_asset_platform.brokers.orders import OrderSide
from ai_asset_platform.execution.order_candidate import OrderCandidate
from ai_asset_platform.execution.paper_order_bridge import execute_paper_order
from ai_asset_platform.execution.service import ExecutionService


def create_service() -> tuple[ExecutionService, Account]:
    broker = SbiPaperAdapter()
    broker.connect()

    account = Account(initial_cash=1_000_000)

    return ExecutionService(
        broker=broker,
        account=account,
    ), account


def test_execute_paper_buy_order():
    service, account = create_service()

    candidate = OrderCandidate(
        symbol="7203.T",
        action="BUY",
        quantity=100,
    )

    fill = execute_paper_order(
        candidate=candidate,
        execution_service=service,
        price=2_500.0,
    )

    assert fill.symbol == "7203.T"
    assert fill.side is OrderSide.BUY
    assert fill.quantity == 100
    assert fill.fill_price == 2_500.0
    assert account.cash == 750_000.0

    position = account.portfolio.get_position("7203.T")

    assert position is not None
    assert position.quantity == 100


def test_execute_paper_sell_order():
    service, account = create_service()

    buy_candidate = OrderCandidate(
        symbol="7203.T",
        action="BUY",
        quantity=100,
    )

    execute_paper_order(
        candidate=buy_candidate,
        execution_service=service,
        price=2_500.0,
    )

    sell_candidate = OrderCandidate(
        symbol="7203.T",
        action="SELL",
        quantity=50,
    )

    fill = execute_paper_order(
        candidate=sell_candidate,
        execution_service=service,
        price=2_700.0,
    )

    assert fill.side is OrderSide.SELL
    assert fill.quantity == 50
    assert account.cash == 885_000.0

    position = account.portfolio.get_position("7203.T")

    assert position is not None
    assert position.quantity == 50


def test_execute_paper_order_rejects_invalid_action():
    service, _ = create_service()

    candidate = OrderCandidate(
        symbol="7203.T",
        action="HOLD",
        quantity=100,
    )

    with pytest.raises(ValueError, match="未対応の売買アクション"):
        execute_paper_order(
            candidate=candidate,
            execution_service=service,
            price=2_500.0,
        )
