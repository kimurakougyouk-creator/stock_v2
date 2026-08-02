from __future__ import annotations

from ai_asset_platform.brokers.base import BrokerAdapter
from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
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

        # 実API接続は次Version以降で追加する。
        self._connected = False
        return False

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

        return OrderResult(
            order_id="IBKR-NOT-IMPLEMENTED",
            status=OrderStatus.REJECTED,
            message="IBKR実注文機能はまだ無効です。",
        )

    def fill_order(
        self,
        order: OrderRequest,
        price: float,
    ) -> FillResult:
        raise RuntimeError(
            "IBKRの実約定処理はまだ有効化されていません。"
        )
