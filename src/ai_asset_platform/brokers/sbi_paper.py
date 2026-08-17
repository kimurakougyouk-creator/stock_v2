"""
SBI証券の模擬接続アダプター
"""

from ai_asset_platform.brokers.base import BrokerAdapter
from ai_asset_platform.brokers.orders import (
    FillResult,
    OrderRecord,
    OrderRequest,
    OrderResult,
    OrderStatus,
)


class SbiPaperAdapter(BrokerAdapter):
    def __init__(self) -> None:
        self._connected = False
        self._next_order_id = 1
        self._order_history: list[OrderRecord] = []

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
            result = OrderResult(
                order_id="NONE",
                status=OrderStatus.REJECTED,
                message="未接続です",
            )
            self._order_history.append(OrderRecord(order, result))
            return result

        order_id = f"PAPER-{self._next_order_id:06d}"
        self._next_order_id += 1

        result = OrderResult(
            order_id=order_id,
            status=OrderStatus.ACCEPTED,
            message="模擬注文を受け付けました",
        )

        self._order_history.append(OrderRecord(order, result))
        return result

    def get_order_history(self) -> list[OrderRecord]:
        return self._order_history.copy()


    def fill_order(self, order: OrderRequest, price: float) -> FillResult:
        result = self.place_order(order)
        if not result.is_accepted:
            raise RuntimeError("注文が受け付けられていません")

        return FillResult(
            order_id=result.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=price,
        )
