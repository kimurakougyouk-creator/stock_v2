import pytest

from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.ibkr_paper_order_sender import (
    prepare_ibkr_paper_order,
)
from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderSide,
    OrderType,
)


def test_prepares_safe_market_buy_without_transmission():
    prepared = prepare_ibkr_paper_order(
        OrderRequest(
            symbol="aapl",
            side=OrderSide.BUY,
            quantity=1,
        ),
        create_ibkr_paper_config(),
    )

    assert prepared.contract.symbol == "AAPL"
    assert prepared.contract.secType == "STK"
    assert prepared.contract.exchange == "SMART"
    assert prepared.contract.currency == "USD"

    assert prepared.order.action == "BUY"
    assert prepared.order.totalQuantity == 1
    assert prepared.order.orderType == "MKT"
    assert prepared.order.transmit is False


def test_prepares_safe_limit_sell_without_transmission():
    prepared = prepare_ibkr_paper_order(
        OrderRequest(
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=1,
            order_type=OrderType.LIMIT,
            limit_price=250.0,
        ),
        create_ibkr_paper_config(),
    )

    assert prepared.order.action == "SELL"
    assert prepared.order.orderType == "LMT"
    assert prepared.order.lmtPrice == 250.0
    assert prepared.order.transmit is False


def test_blocks_quantity_greater_than_one():
    with pytest.raises(RuntimeError, match="数量1"):
        prepare_ibkr_paper_order(
            OrderRequest(
                symbol="AAPL",
                side=OrderSide.BUY,
                quantity=2,
            ),
            create_ibkr_paper_config(),
        )


def test_blocks_non_paper_configuration():
    with pytest.raises(RuntimeError, match="Paper Trading設定ではない"):
        prepare_ibkr_paper_order(
            OrderRequest(
                symbol="AAPL",
                side=OrderSide.BUY,
                quantity=1,
            ),
            IbkrConnectionConfig(
                port=7496,
                paper_trading=False,
                allow_live_trading=True,
            ),
        )


def test_blocks_live_permission_even_on_paper_config():
    with pytest.raises(RuntimeError, match="Live Trading許可中"):
        prepare_ibkr_paper_order(
            OrderRequest(
                symbol="AAPL",
                side=OrderSide.BUY,
                quantity=1,
            ),
            IbkrConnectionConfig(
                port=7497,
                paper_trading=True,
                allow_live_trading=True,
            ),
        )
