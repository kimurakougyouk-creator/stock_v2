from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Callable

from ai_asset_platform.brokers.ibkr_fill_pipeline import IbkrFillPipeline
from ai_asset_platform.brokers.ibkr_fill_state import IbkrFillStateStore
from ai_asset_platform.brokers.ibkr_fill_tracker import IbkrFillTracker
from ai_asset_platform.brokers.ibkr_order_events import (
    IbkrOrderStatusEvent,
    create_ibkr_order_status_event,
)
from ai_asset_platform.brokers.orders import FillResult, OrderRequest


class IbkrFillRuntime:
    """IBKR orderStatusを差分約定へ変換し、安全に永続化する。"""

    def __init__(
        self,
        state_path: str | Path,
        *,
        on_fill: Callable[[FillResult], None] | None = None,
    ) -> None:
        self._store = IbkrFillStateStore(state_path)
        self._tracker = IbkrFillTracker()
        self._tracker.restore(self._store.load())
        self._pipeline = IbkrFillPipeline(self._tracker)
        self._orders: dict[int, OrderRequest] = {}
        self._on_fill = on_fill
        self._lock = Lock()

    def register_order(self, order_id: int, request: OrderRequest) -> None:
        if order_id < 0:
            raise ValueError("IBKR order_idは0以上にしてください。")
        with self._lock:
            self._orders[order_id] = request

    def unregister_order(self, order_id: int) -> None:
        with self._lock:
            self._orders.pop(order_id, None)

    def process_order_status(
        self,
        order_id: int,
        status: str,
        filled: float,
        remaining: float,
        average_fill_price: float,
    ) -> FillResult | None:
        event = create_ibkr_order_status_event(
            order_id=order_id,
            status=status,
            filled=filled,
            remaining=remaining,
            average_fill_price=average_fill_price,
        )
        return self.process_event(event)

    def process_event(
        self,
        event: IbkrOrderStatusEvent,
    ) -> FillResult | None:
        with self._lock:
            request = self._orders.get(event.order_id)
            if request is None:
                return None

            result = self._pipeline.process(request, event)
            self._store.save(self._tracker.snapshot())

            if result is not None and self._on_fill is not None:
                self._on_fill(result)

            return result

    def processed_filled(self, order_id: int) -> float:
        with self._lock:
            return self._tracker.processed_filled(order_id)
