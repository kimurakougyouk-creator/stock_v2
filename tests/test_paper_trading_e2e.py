from ai_asset_platform.account import Account
from ai_asset_platform.brokers.orders import OrderSide
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter
from ai_asset_platform.decision.signal_selector import TradingSignal
from ai_asset_platform.execution.order_candidate import create_order_candidate
from ai_asset_platform.execution.paper_order_bridge import execute_paper_order
from ai_asset_platform.execution.service import ExecutionService


def test_paper_trading_buy_sell_e2e():
    """
    売買シグナルからPaper約定・口座反映までを
    一連の流れとして確認する。
    """

    broker = SbiPaperAdapter()
    assert broker.connect() is True

    account = Account(initial_cash=1_000_000)

    execution_service = ExecutionService(
        broker=broker,
        account=account,
    )

    buy_signal = TradingSignal(
        symbol="7203.T",
        action="BUY",
        confidence=90.0,
    )

    buy_candidate = create_order_candidate(
        signal=buy_signal,
        quantity=100,
    )

    buy_fill = execute_paper_order(
        candidate=buy_candidate,
        execution_service=execution_service,
        price=2_500.0,
    )

    assert buy_fill.side is OrderSide.BUY
    assert buy_fill.quantity == 100
    assert buy_fill.fill_price == 2_500.0

    assert account.cash == 750_000.0

    position = account.portfolio.get_position("7203.T")

    assert position is not None
    assert position.quantity == 100

    sell_signal = TradingSignal(
        symbol="7203.T",
        action="SELL",
        confidence=95.0,
    )

    sell_candidate = create_order_candidate(
        signal=sell_signal,
        quantity=50,
    )

    sell_fill = execute_paper_order(
        candidate=sell_candidate,
        execution_service=execution_service,
        price=2_700.0,
    )

    assert sell_fill.side is OrderSide.SELL
    assert sell_fill.quantity == 50
    assert sell_fill.fill_price == 2_700.0

    assert account.cash == 885_000.0

    remaining_position = account.portfolio.get_position("7203.T")

    assert remaining_position is not None
    assert remaining_position.quantity == 50

    history = broker.get_order_history()

    assert len(history) == 2
    assert history[0].request.side is OrderSide.BUY
    assert history[1].request.side is OrderSide.SELL

    broker.disconnect()

    assert broker.is_connected() is False
