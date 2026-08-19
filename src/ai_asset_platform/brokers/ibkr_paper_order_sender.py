from __future__ import annotations

from dataclasses import dataclass

from ibapi.contract import Contract
from ibapi.order import Order

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderSide,
    OrderType,
)


@dataclass(frozen=True)
class IbkrPreparedOrder:
    contract: Contract
    order: Order


def prepare_ibkr_paper_order(
    request: OrderRequest,
    config: IbkrConnectionConfig,
) -> IbkrPreparedOrder:
    """
    共通OrderRequestをIBKR API形式へ安全に変換する。

    この関数は注文を送信しない。
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

    if request.quantity != 1:
        raise RuntimeError(
            "初回IBKR Paperテスト注文は数量1だけ許可します。"
        )

    contract = Contract()
    contract.symbol = request.symbol.strip().upper()
    contract.secType = "STK"
    contract.exchange = "SMART"
    contract.currency = "USD"

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
