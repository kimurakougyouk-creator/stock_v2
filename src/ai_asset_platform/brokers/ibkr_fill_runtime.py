from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Callable

from ai_asset_platform.brokers.ibkr_execution_ledger import IbkrExecutionLedger
from ai_asset_platform.brokers.ibkr_fill_pipeline import IbkrFillPipeline
from ai_asset_platform.brokers.ibkr_fill_state import IbkrFillStateStore
from ai_asset_platform.brokers.ibkr_fill_tracker import IbkrFillTracker
from ai_asset_platform.brokers.ibkr_order_events import (
    IbkrOrderState,
    IbkrOrderStatusEvent,
    create_ibkr_order_status_event,
)
from ai_asset_platform.brokers.orders import FillResult, OrderRequest


class IbkrFillRuntime:
    """IBKR orderStatus/execDetailsを差分約定へ変換し、安全に永続化する。"""

    def __init__(
        self,
        state_path: str | Path,
        *,
        on_fill: Callable[[FillResult], None] | None = None,
    ) -> None:
        self._store = IbkrFillStateStore(state_path)
        self._tracker = IbkrFillTracker()
        self._tracker.restore(self._store.load())
        self._execution_ledger = IbkrExecutionLedger()
        self._execution_ledger.restore(self._store.load_execution_ledger())
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
        with self._lock:
            event = self._safe_delta_event(
                order_id=order_id,
                status=status,
                filled=filled,
                remaining=remaining,
                average_fill_price=average_fill_price,
            )
            return self._process_event_locked(event)

    def process_execution(
        self,
        order_id: int,
        exec_id: str,
        shares: float,
        price: float,
    ) -> FillResult | None:
        """
        execDetailsから得た約定をexecId単位で冪等に処理する。

        複数回の部分約定は、累積約定株数と
        (累積約定金額 ÷ 累積約定数量)の加重平均価格へ正しく反映される。
        orderStatus由来のイベントと同じ既存パイプライン(process_event)を
        再利用するため、この関数は合成イベントを組み立てるだけで、
        約定判定・永続化・重複排除ロジック自体は新規実装しない。
        """
        with self._lock:
            cumulative_shares, weighted_avg_price = (
                self._execution_ledger.record_execution(
                    order_id, exec_id, shares, price
                )
            )

            event = self._safe_delta_event(
                order_id=order_id,
                status=IbkrOrderState.FILLED.value,
                filled=cumulative_shares,
                remaining=0.0,
                average_fill_price=weighted_avg_price,
            )
            return self._process_event_locked(event)

    def process_event(
        self,
        event: IbkrOrderStatusEvent,
    ) -> FillResult | None:
        with self._lock:
            return self._process_event_locked(event)

    def _safe_delta_event(
        self,
        *,
        order_id: int,
        status: str,
        filled: float,
        remaining: float,
        average_fill_price: float,
    ) -> IbkrOrderStatusEvent:
        """
        orderStatusとexecDetailsは独立した2つのソースであり、
        到着順序次第で一方が他方より一時的に低い累積値を報告し得る。
        IbkrFillTrackerへ後退した値を渡すと例外になるため、
        既に判明している累積値を下回らない値だけを渡す。
        (呼び出し元で self._lock を保持済みであることが前提)
        """
        already_processed = self._tracker.processed_filled(order_id)
        effective_filled = max(filled, already_processed)

        return create_ibkr_order_status_event(
            order_id=order_id,
            status=status,
            filled=effective_filled,
            remaining=remaining,
            average_fill_price=average_fill_price,
        )

    def _process_event_locked(
        self,
        event: IbkrOrderStatusEvent,
    ) -> FillResult | None:
        request = self._orders.get(event.order_id)
        if request is None:
            return None

        result = self._pipeline.process(request, event)
        self._store.save(
            self._tracker.snapshot(),
            self._execution_ledger.snapshot(),
        )

        if result is not None and self._on_fill is not None:
            self._on_fill(result)

        return result

    def processed_filled(self, order_id: int) -> float:
        with self._lock:
            return self._tracker.processed_filled(order_id)
