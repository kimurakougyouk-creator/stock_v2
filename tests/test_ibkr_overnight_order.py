import pytest

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_overnight_order import OvernightPaperOrderSpec, prepare_ibkr_overnight_paper_limit_order
from ai_asset_platform.brokers.orders import OrderSide
from ai_asset_platform.core.asset_classes import AssetClass


def test_verified_spy_overnight_order_is_limit_day_and_never_transmits():
    prepared = prepare_ibkr_overnight_paper_limit_order(
        OvernightPaperOrderSpec(
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=1,
            limit_price=500.00,
            primary_exchange="ARCA",
            asset_class=AssetClass.ETF,
        ),
        verified_paper_test_quantity=1,
    )
    assert prepared.contract.symbol == "SPY"
    assert prepared.contract.secType == "STK"
    assert prepared.contract.exchange == "OVERNIGHT"
    assert prepared.contract.primaryExchange == "ARCA"
    assert prepared.order.action == "BUY"
    assert prepared.order.totalQuantity == 1
    assert prepared.order.orderType == "LMT"
    assert prepared.order.lmtPrice == 500.00
    assert prepared.order.tif == "DAY"
    assert prepared.order.outsideRth is False
    assert prepared.order.transmit is False


def test_overnight_order_blocks_unverified_quantity():
    with pytest.raises(RuntimeError, match="unverified"):
        prepare_ibkr_overnight_paper_limit_order(
            OvernightPaperOrderSpec(
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=1,
                limit_price=500.00,
                primary_exchange="ARCA",
            )
        )


def test_overnight_order_rejects_quantity_mismatch():
    with pytest.raises(RuntimeError, match="検証済み数量1"):
        prepare_ibkr_overnight_paper_limit_order(
            OvernightPaperOrderSpec(
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=2,
                limit_price=500.00,
                primary_exchange="ARCA",
            ),
            verified_paper_test_quantity=1,
        )


def test_overnight_order_rejects_non_us_stock_etf_asset_class():
    with pytest.raises(ValueError, match="US STOCK/ETF"):
        prepare_ibkr_overnight_paper_limit_order(
            OvernightPaperOrderSpec(
                symbol="ES",
                side=OrderSide.BUY,
                quantity=1,
                limit_price=5000.0,
                primary_exchange="CME",
                asset_class=AssetClass.FUTURE,
            ),
            verified_paper_test_quantity=1,
        )


def test_overnight_order_rejects_gateway_port():
    with pytest.raises(RuntimeError, match="7497"):
        prepare_ibkr_overnight_paper_limit_order(
            OvernightPaperOrderSpec(
                symbol="SPY",
                side=OrderSide.BUY,
                quantity=1,
                limit_price=500.00,
                primary_exchange="ARCA",
            ),
            config=IbkrConnectionConfig(port=4002),
            verified_paper_test_quantity=1,
        )
