from ai_asset_platform.brokers.orders import OrderRequest


class OrderQueue:
    def __init__(self) -> None:
        self._orders: list[OrderRequest] = []

    def enqueue(self, order: OrderRequest) -> None:
        self._orders.append(order)

    def dequeue(self) -> OrderRequest | None:
        if not self._orders:
            return None

        return self._orders.pop(0)

    def __len__(self) -> int:
        return len(self._orders)
