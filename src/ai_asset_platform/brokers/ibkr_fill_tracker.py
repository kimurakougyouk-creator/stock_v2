from __future__ import annotations

from dataclasses import dataclass, field

from ai_asset_platform.brokers.ibkr_order_events import IbkrOrderStatusEvent


@dataclass
class IbkrFillTracker:
    """IBKRの累積約定数量から、新しく増えた約定数量だけを取り出す。"""

    _processed_filled: dict[int, float] = field(default_factory=dict)

    def get_fill_delta(self, event: IbkrOrderStatusEvent) -> float:
        if event.filled < 0:
            raise ValueError("IBKR filledは0以上にしてください。")

        previous = self._processed_filled.get(event.order_id, 0.0)

        if event.filled < previous:
            raise ValueError(
                "IBKR累積約定数量が前回値より減少しています。"
            )

        delta = event.filled - previous
        self._processed_filled[event.order_id] = event.filled
        return delta

    def processed_filled(self, order_id: int) -> float:
        return self._processed_filled.get(order_id, 0.0)

    def snapshot(self) -> dict[int, float]:
        return dict(self._processed_filled)

    def restore(self, processed_filled: dict[int, float]) -> None:
        restored: dict[int, float] = {}

        for order_id, quantity in processed_filled.items():
            if order_id < 0:
                raise ValueError("IBKR order_idは0以上にしてください。")

            if quantity < 0:
                raise ValueError(
                    "IBKR処理済み約定数量は0以上にしてください。"
                )

            restored[int(order_id)] = float(quantity)

        self._processed_filled = restored

    def clear(self, order_id: int) -> None:
        self._processed_filled.pop(order_id, None)
