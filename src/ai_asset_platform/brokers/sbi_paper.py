"""
SBI証券の模擬接続アダプター
"""

from ai_asset_platform.brokers.base import BrokerAdapter
from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderResult,
    OrderStatus,
)


class SbiPaperAdapter(BrokerAdapter):
    def __init__(self) -> None:
        self._connected = False
        self._next_order_id = 1

    @property
    def name(self) -> str:
        return "SBI_PAPER"

    def connect(self) -> bool:
        self._connected = True
        return True

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def place_order(self, order: OrderRequest) -> OrderResult:
        if not self._connected:
            return OrderResult(
                order_id="NONE",
                status=OrderStatus.REJECTED,
                message="未接続です",
            )

        order_id = f"PAPER-{self._next_order_id:06d}"
        self._next_order_id += 1

        return OrderResult(
            order_id=order_id,
            status=OrderStatus.ACCEPTED,
            message="模擬注文を受け付けました",
        )
