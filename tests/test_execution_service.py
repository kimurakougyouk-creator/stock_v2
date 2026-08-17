from ai_asset_platform.account import Account
from ai_asset_platform.brokers.orders import OrderSide
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter
from ai_asset_platform.execution.service import ExecutionService


def test_execution_service_buy_sell_and_reject() -> None:
    broker = SbiPaperAdapter()
    account = Account(initial_cash=1_000_000)
    execution = ExecutionService(
        broker=broker,
        account=account,
    )

    assert broker.connect() is True

    buy_fill = execution.execute_market_order(
        symbol="7203.T",
        side=OrderSide.BUY,
        quantity=100,
        price=2500.0,
    )

    position = account.portfolio.get_position("7203.T")

    assert buy_fill.order_id == "PAPER-000001"
    assert account.cash == 750_000.0
    assert position is not None
    assert position.quantity == 100
    assert position.average_price == 2500.0

    sell_fill = execution.execute_market_order(
        symbol="7203.T",
        side=OrderSide.SELL,
        quantity=40,
        price=3000.0,
    )

    position = account.portfolio.get_position("7203.T")

    assert sell_fill.order_id == "PAPER-000002"
    assert account.cash == 870_000.0
    assert position is not None
    assert position.quantity == 60
    assert account.portfolio.realized_pnl == 20_000.0

    history_before = len(broker.get_order_history())

    try:
        execution.execute_market_order(
            symbol="7203.T",
            side=OrderSide.SELL,
            quantity=1000,
            price=3000.0,
        )
    except ValueError as error:
        assert str(error) == "保有数量を超えて売却できません"
    else:
        raise AssertionError("不正な売却注文が拒否されませんでした")

    history_after = len(broker.get_order_history())

    assert history_before == history_after
