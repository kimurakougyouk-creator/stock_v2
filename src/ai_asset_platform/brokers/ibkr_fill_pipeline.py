from __future__ import annotations

from dataclasses import replace

from ai_asset_platform.brokers.ibkr_fill_bridge import (
    convert_ibkr_event_to_fill,
)
from ai_asset_platform.brokers.ibkr_fill_tracker import IbkrFillTracker
from ai_asset_platform.brokers.ibkr_order_events import IbkrOrderStatusEvent
from ai_asset_platform.brokers.orders import FillResult, OrderRequest


class IbkrFillPipeline:
    """
    IBKRの累積約定イベントを、安全な差分FillResultへ変換する。

    流れ:
    IBKR event
      -> 累積filledの差分を計算
      -> 新規約定がなければNone
      -> 差分数量だけFillResultへ変換

    注文送信・口座更新は行わない。
    """

    def __init__(self, tracker: IbkrFillTracker | None = None) -> None:
        self._tracker = tracker or IbkrFillTracker()

    def process(
        self,
        request: OrderRequest,
        event: IbkrOrderStatusEvent,
    ) -> FillResult | None:
        if event.filled > request.quantity:
            raise ValueError("IBKR約定数量が注文数量を超えています。")

        delta = self._tracker.get_fill_delta(event)

        if delta <= 0:
            return None

        if not float(delta).is_integer():
            raise ValueError(
                "現在のOrderRequestは整数数量のため、"
                "小数の約定数量には対応していません。"
            )

        delta_event = replace(
            event,
            filled=int(delta),
        )

        return convert_ibkr_event_to_fill(
            request=request,
            event=delta_event,
        )

    def processed_filled(self, order_id: int) -> float:
        return self._tracker.processed_filled(order_id)

    def clear(self, order_id: int) -> None:
        self._tracker.clear(order_id)
