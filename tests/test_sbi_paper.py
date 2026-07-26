import unittest

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter


class TestSbiPaperAdapter(unittest.TestCase):
    def setUp(self):
        self.broker = SbiPaperAdapter()

    def test_order_is_rejected_when_disconnected(self):
        order = OrderRequest("7203.T", OrderSide.BUY, 100)
        result = self.broker.place_order(order)

        self.assertFalse(result.is_accepted)
        self.assertEqual(len(self.broker.get_order_history()), 1)

    def test_order_record_contains_request_and_result(self):
        self.broker.connect()
        order = OrderRequest("7203.T", OrderSide.BUY, 100)

        result = self.broker.place_order(order)
        record = self.broker.get_order_history()[0]

        self.assertEqual(record.request, order)
        self.assertEqual(record.result, result)
        self.assertEqual(record.request.symbol, "7203.T")
        self.assertEqual(record.request.quantity, 100)
        self.assertTrue(record.result.is_accepted)

    def test_history_returns_copy(self):
        self.broker.connect()
        self.broker.place_order(
            OrderRequest("7203.T", OrderSide.BUY, 100)
        )

        history = self.broker.get_order_history()
        history.clear()

        self.assertEqual(len(self.broker.get_order_history()), 1)


if __name__ == "__main__":
    unittest.main()
