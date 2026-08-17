from __future__ import annotations

from ai_asset_platform.brokers.ibkr_order_events import (
    IbkrOrderState,
    IbkrOrderStatusEvent,
)
from ai_asset_platform.brokers.orders import (
    FillResult,
    OrderRequest,
)


def convert_ibkr_event_to_fill(
    request: OrderRequest,
    event: IbkrOrderStatusEvent,
) -> FillResult | None:
    """
    IBKRの注文状態イベントを既存FillResultへ安全に変換する。

    約定が発生していないイベントはNoneを返す。
    実注文の送信や口座更新は行わない。
    """
    if not event.has_fill:
        return None

    if event.status not in {
        IbkrOrderState.SUBMITTED,
        IbkrOrderState.FILLED,
    }:
        return None

    if event.average_fill_price <= 0:
        raise ValueError("約定価格は0より大きい必要があります。")

    if event.filled <= 0:
        return None

    if event.filled > request.quantity:
        raise ValueError("IBKR約定数量が注文数量を超えています。")

    return FillResult(
        order_id=str(event.order_id),
        symbol=request.symbol,
        side=request.side,
        quantity=event.filled,
        fill_price=event.average_fill_price,
    )
