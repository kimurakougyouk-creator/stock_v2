from ai_asset_platform.execution.order_queue import OrderQueue
from ai_asset_platform.execution.order_request import OrderRequest


def test_enqueue_and_dequeue():
    queue = OrderQueue()

    order = OrderRequest(
        symbol="7203.T",
        action="BUY",
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
