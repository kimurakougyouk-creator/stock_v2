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
    """共通OrderRequestと明示的InstrumentSpecをIBKR API形式へ安全に変換する。

    この関数は注文を送信しない。数量はInstrumentSpecに明示された
    broker-verified Paperテスト数量と完全一致する場合だけ許可する。
    """
    config.validate()

    if not config.paper_trading:
        raise RuntimeError(
            "Paper Trading設定ではないためIBKR注文準備を中止しました。"
        )

    if config.allow_live_trading:
        raise RuntimeError(
            "Live Trading許可中のためIBKR注文準備を中止しました。"
        )

    verified_quantity = instrument.verified_paper_test_quantity
    if verified_quantity is None:
        raise RuntimeError(
            "この銘柄のIBKR Paper検証済み注文数量が未登録のため停止しました。"
        )
    if request.quantity != verified_quantity:
        raise RuntimeError(
            f"IBKR Paperテスト注文は検証済み数量{verified_quantity}だけ許可します。"
        )

    request_symbol = request.symbol.strip().upper()
    instrument_symbol = instrument.symbol.strip().upper()
    if request_symbol != instrument_symbol:
        raise ValueError("OrderRequestとInstrumentSpecのsymbolが一致しません。")

    contract = to_ibapi_contract(build_ibkr_contract_spec(instrument))

    ib_order = Order()
    ib_order.action = (
        "BUY" if request.side is OrderSide.BUY else "SELL"
    )
    ib_order.totalQuantity = request.quantity
    # ibapiのOrder既定値は空文字列("Time in Force"未設定)であり、
    # IBKRはこれをエラー10052「無効な有効期限:空白」として拒否する。
    ib_order.tif = "DAY"

    if request.order_type is OrderType.MARKET:
        ib_order.orderType = "MKT"
    elif request.order_type is OrderType.LIMIT:
        ib_order.orderType = "LMT"
        ib_order.lmtPrice = request.limit_price
    else:
        raise ValueError(
            f"未対応のIBKR注文種別です: {request.order_type}"
        )

    # 注文準備段階では安全のため送信を無効化する。
    ib_order.transmit = False

    return IbkrPreparedOrder(
        contract=contract,
        order=ib_order,
    )


def prepare_ibkr_paper_order(
    request: OrderRequest,
    config: IbkrConnectionConfig,
) -> IbkrPreparedOrder:
    """既存US株向けの後方互換Paper注文準備入口。"""
    instrument = InstrumentSpec(
        symbol=request.symbol.strip().upper(),
        asset_class=AssetClass.STOCK,
    )
    return prepare_ibkr_paper_order_for_instrument(request, instrument, config)
