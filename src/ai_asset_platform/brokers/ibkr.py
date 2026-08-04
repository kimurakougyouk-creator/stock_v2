from __future__ import annotations

from ai_asset_platform.brokers.base import BrokerAdapter
from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.ibkr_connection import (
    probe_ibkr_paper_connection,
)
from ai_asset_platform.brokers.ibkr_paper_order_sender import (
    prepare_ibkr_paper_order,
)
from ai_asset_platform.brokers.orders import (
    FillResult,
    OrderRequest,
    OrderResult,
    OrderStatus,
)


class IbkrBrokerAdapter(BrokerAdapter):
    """
    IBKR用Broker Adapterの安全な土台。

    Version 13.3では実際のIBKR API通信・発注はまだ行わない。
    """

    def __init__(
        self,
        config: IbkrConnectionConfig | None = None,
    ) -> None:
        self.config = config or create_ibkr_paper_config()
        self._connected = False

    @property
    def name(self) -> str:
        return "IBKR"

    def connect(self) -> bool:
        self.config.validate()

        result = probe_ibkr_paper_connection(
            self.config,
        )

        self._connected = result.connected
        return self._connected

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def place_order(self, order: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(
                order_id="IBKR-NOT-CONNECTED",
                status=OrderStatus.REJECTED,
                message="IBKRへ接続されていないため注文しません。",
            )

        prepared = prepare_ibkr_paper_order(
            order,
            self.config,
        )

        if prepared.order.transmit:
            raise RuntimeError(
                "安全停止: IBKR Paper注文のtransmitが有効です。"
            )

        return OrderResult(
            order_id="IBKR-PAPER-PREPARED",
            status=OrderStatus.REJECTED,
            message=(
                "IBKR Paper注文の安全な準備まで完了しました。"
                "注文は送信していません。"
            ),
        )

    def fill_order(
        self,
        order: OrderRequest,
        price: float,
    ) -> FillResult:
        raise RuntimeError(
            "IBKRの実約定処理はまだ有効化されていません。"
        )
