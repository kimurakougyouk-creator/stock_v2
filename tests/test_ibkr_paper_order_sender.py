import pytest

from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.ibkr_paper_order_sender import (
    prepare_ibkr_paper_order,
    prepare_ibkr_paper_order_for_instrument,
)
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderSide,
    OrderType,
)
from ai_asset_platform.core.asset_classes import AssetClass


def test_prepares_safe_market_buy_without_transmission():
    prepared = prepare_ibkr_paper_order(
        OrderRequest(symbol="aapl", side=OrderSide.BUY, quantity=1),
        create_ibkr_paper_config(),
    )
    assert prepared.contract.symbol == "AAPL"
    assert prepared.contract.secType == "STK"
    assert prepared.contract.exchange == "SMART"
    assert prepared.contract.currency == "USD"
    assert prepared.order.action == "BUY"
    assert prepared.order.totalQuantity == 1
    assert prepared.order.orderType == "MKT"
    assert prepared.order.tif == "DAY"
    assert prepared.order.transmit is False


def test_prepares_safe_limit_sell_without_transmission():
    prepared = prepare_ibkr_paper_order(
        OrderRequest(symbol="AAPL", side=OrderSide.SELL, quantity=1, order_type=OrderType.LIMIT, limit_price=250.0),
        create_ibkr_paper_config(),
    )
    assert prepared.order.action == "SELL"
    assert prepared.order.orderType == "LMT"
    assert prepared.order.lmtPrice == 250.0
    assert prepared.order.tif == "DAY"
    assert prepared.order.transmit is False


def test_tif_is_always_set_to_day_not_left_blank():
    prepared = prepare_ibkr_paper_order(
        OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1),
        create_ibkr_paper_config(),
    )
    assert prepared.order.tif == "DAY"
    assert prepared.order.tif != ""


def test_legacy_path_still_blocks_quantity_greater_than_one():
    with pytest.raises(RuntimeError, match="検証済み数量1"):
        prepare_ibkr_paper_order(
            OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=2),
            create_ibkr_paper_config(),
        )


def test_explicit_instrument_allows_exact_verified_quantity():
    instrument = InstrumentSpec(
        symbol="9432",
        asset_class=AssetClass.STOCK,
        exchange="TSEJ",
        currency="JPY",
        verified_paper_test_quantity=100,
    )
    prepared = prepare_ibkr_paper_order_for_instrument(
        OrderRequest(symbol="9432", side=OrderSide.BUY, quantity=100),
        instrument,
        create_ibkr_paper_config(),
    )
    assert prepared.contract.symbol == "9432"
    assert prepared.contract.exchange == "TSEJ"
    assert prepared.contract.currency == "JPY"
    assert prepared.order.totalQuantity == 100
    assert prepared.order.transmit is False


def test_explicit_instrument_blocks_quantity_mismatch():
    instrument = InstrumentSpec(
        symbol="9432",
        asset_class=AssetClass.STOCK,
        exchange="TSEJ",
        currency="JPY",
        verified_paper_test_quantity=100,
    )
    with pytest.raises(RuntimeError, match="検証済み数量100"):
        prepare_ibkr_paper_order_for_instrument(
            OrderRequest(symbol="9432", side=OrderSide.BUY, quantity=1),
            instrument,
            create_ibkr_paper_config(),
        )


def test_explicit_instrument_without_verified_quantity_fails_closed():
    instrument = InstrumentSpec(
        symbol="9432",
        asset_class=AssetClass.STOCK,
        exchange="TSEJ",
        currency="JPY",
        verified_paper_test_quantity=None,
    )
    with pytest.raises(RuntimeError, match="未登録"):
        prepare_ibkr_paper_order_for_instrument(
            OrderRequest(symbol="9432", side=OrderSide.BUY, quantity=100),
            instrument,
            create_ibkr_paper_config(),
        )


def test_blocks_non_paper_configuration():
    with pytest.raises(RuntimeError, match="Paper Trading設定ではない"):
        prepare_ibkr_paper_order(
            OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1),
            IbkrConnectionConfig(port=7496, paper_trading=False, allow_live_trading=True),
        )


def test_blocks_live_permission_even_on_paper_config():
    with pytest.raises(RuntimeError, match="Live Trading許可中"):
        prepare_ibkr_paper_order(
            OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1),
            IbkrConnectionConfig(port=7497, paper_trading=True, allow_live_trading=True),
        )
