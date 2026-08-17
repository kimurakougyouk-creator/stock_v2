from __future__ import annotations

from pathlib import Path
from typing import Callable

from ai_asset_platform.brokers.base import BrokerAdapter
from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.ibkr_fill_runtime import IbkrFillRuntime
from ai_asset_platform.brokers.ibkr_paper_transmitter import (
    transmit_ibkr_paper_order,
)
from ai_asset_platform.brokers.ibkr_session import (
    IbkrPaperSession,
    open_ibkr_paper_session,
)
from ai_asset_platform.brokers.orders import (
    FillResult,
    OrderRequest,
    OrderResult,
    OrderStatus,
)


class IbkrBrokerAdapter(BrokerAdapter):
    """IBKR Paper Trading用Broker Adapter。

    接続、Paper注文、orderStatus、差分約定、永続化を一か所に統合する。
    注文送信はデフォルトで無効。Live Tradingは許可しない。
    """

    def __init__(
        self,
        config: IbkrConnectionConfig | None = None,
        *,
        enable_paper_order_transmission: bool = False,
        fill_state_path: str | Path = "data/ibkr_fill_state.json",
        on_fill: Callable[[FillResult], None] | None = None,
    ) -> None:
        self.config = config or create_ibkr_paper_config()
        self._session: IbkrPaperSession | None = None
        self._enable_paper_order_transmission = enable_paper_order_transmission
        self._fill_runtime = IbkrFillRuntime(
            fill_state_path,
            on_fill=on_fill,
        )

    @property
    def name(self) -> str:
        return "IBKR"

    def connect(self) -> bool:
        self.config.validate()

        if self.is_connected():
            return True

        self._session = open_ibkr_paper_session(
            self.config,
            order_status_handler=self._fill_runtime.process_order_status,
            exec_details_handler=self._fill_runtime.process_execution,
        )
        return self.is_connected()

    def is_connected(self) -> bool:
        return self._session is not None and self._session.connected

    def disconnect(self) -> None:
        if self._session is not None:
            self._session.disconnect()
        self._session = None

    def place_order(self, order: OrderRequest) -> OrderResult:
        if not self.is_connected() or self._session is None:
            return OrderResult(
                order_id="IBKR-NOT-CONNECTED",
                status=OrderStatus.REJECTED,
                message="IBKRへ接続されていないため注文しません。",
            )

        result = transmit_ibkr_paper_order(
            order,
            self.config,
            client=self._session.client,
            next_order_id=self._session.next_order_id,
            enable_transmission=self._enable_paper_order_transmission,
        )

        if not result.sent:
            return OrderResult(
                order_id=(
                    str(result.order_id)
                    if result.order_id is not None
                    else "IBKR-PAPER-NOT-SENT"
                ),
                status=OrderStatus.REJECTED,
                message=result.message,
            )

        if result.order_id is None:
            return OrderResult(
                order_id="IBKR-PAPER-MISSING-ORDER-ID",
                status=OrderStatus.REJECTED,
                message="IBKR Paper注文IDを確認できませんでした。",
            )

        self._fill_runtime.register_order(result.order_id, order)
        self._session.next_order_id += 1

        return OrderResult(
            order_id=str(result.order_id),
            status=OrderStatus.ACCEPTED,
            message=result.message,
        )

    def processed_filled(self, order_id: int) -> float:
        return self._fill_runtime.processed_filled(order_id)

    def fill_order(
        self,
        order: OrderRequest,
        price: float,
    ) -> FillResult:
        raise RuntimeError(
            "IBKRの手動実約定処理は有効化されていません。"
        )
