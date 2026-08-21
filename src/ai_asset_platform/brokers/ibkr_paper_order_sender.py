from __future__ import annotations

from dataclasses import dataclass

from ibapi.contract import Contract
from ibapi.order import Order

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_contracts import (
    build_ibkr_contract_spec,
    to_ibapi_contract,
)
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderSide,
    OrderType,
)
from ai_asset_platform.core.asset_classes import AssetClass


@dataclass(frozen=True)
class IbkrPreparedOrder:
    contract: Contract
    order: Order


def prepare_ibkr_paper_order_for_instrument(
    request: OrderRequest,
    instrument: InstrumentSpec,
    config: IbkrConnectionConfig,
) -> IbkrPreparedOrder:
    """Prepare, but never transmit, an IBKR Paper order for an explicit instrument."""
    config.validate()

    if not config.paper_trading:
        raise RuntimeError(
            "Paper Trading設定ではないためIBKR注文準備を中止しました。"
        )
    if config.allow_live_trading:
        raise RuntimeError(
            "Live Trading許可中のためIBKR注文準備を中止しました。"
        )
    if request.quantity != 1:
        raise RuntimeError(
            "初回IBKR Paperテスト注文は数量1だけ許可します。"
        )

    request_symbol = request.symbol.strip().upper()
    instrument_symbol = instrument.symbol.strip().upper()
    if request_symbol != instrument_symbol:
        raise ValueError("OrderRequestとInstrumentSpecのsymbolが一致しません。")

    contract = to_ibapi_contract(build_ibkr_contract_spec(instrument))

    ib_order = Order()
    ib_order.action = "BUY" if request.side is OrderSide.BUY else "SELL"
    ib_order.totalQuantity = request.quantity
    ib_order.tif = "DAY"

    if request.order_type is OrderType.MARKET:
        ib_order.orderType = "MKT"
    elif request.order_type is OrderType.LIMIT:
        ib_order.orderType = "LMT"
        ib_order.lmtPrice = request.limit_price
    else:
        raise ValueError(f"未対応のIBKR注文種別です: {request.order_type}")

    # This module only prepares orders. Transmission remains disabled.
    ib_order.transmit = False
    return IbkrPreparedOrder(contract=contract, order=ib_order)


def prepare_ibkr_paper_order(
    request: OrderRequest,
    config: IbkrConnectionConfig,
) -> IbkrPreparedOrder:
    """Backward-compatible US-stock Paper preparation entry point."""
    instrument = InstrumentSpec(
        symbol=request.symbol.strip().upper(),
        asset_class=AssetClass.STOCK,
    )
    return prepare_ibkr_paper_order_for_instrument(request, instrument, config)
