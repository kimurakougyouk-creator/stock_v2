from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.execution.order_queue import OrderQueue


def test_enqueue_and_dequeue():
    queue = OrderQueue()

    order = OrderRequest(
        symbol="7203.T",
        side=OrderSide.BUY,
        quantity=100,
    )

    queue.enqueue(order)

    assert len(queue) == 1
    assert queue.dequeue() == order
    assert len(queue) == 0


def test_dequeue_empty_queue():
    queue = OrderQueue()

    assert queue.dequeue() is None
    assert len(queue) == 0
