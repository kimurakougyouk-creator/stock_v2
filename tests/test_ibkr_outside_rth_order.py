from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_paper_order_sender import prepare_ibkr_paper_order_for_instrument
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass


def test_outside_rth_defaults_off():
    request = OrderRequest("SPY", OrderSide.SELL, 1, OrderType.LIMIT, 700.0)
    instrument = InstrumentSpec("SPY", AssetClass.ETF, exchange="SMART", currency="USD", verified_paper_test_quantity=1)
    prepared = prepare_ibkr_paper_order_for_instrument(request, instrument, create_ibkr_paper_config(use_gateway=True))
    assert prepared.order.outsideRth is False


def test_outside_rth_is_explicitly_propagated():
    request = OrderRequest("SPY", OrderSide.SELL, 1, OrderType.LIMIT, 700.0, outside_rth=True)
    instrument = InstrumentSpec("SPY", AssetClass.ETF, exchange="SMART", currency="USD", verified_paper_test_quantity=1)
    prepared = prepare_ibkr_paper_order_for_instrument(request, instrument, create_ibkr_paper_config(use_gateway=True))
    assert prepared.order.outsideRth is True
