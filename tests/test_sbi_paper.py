import unittest

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter


class TestSbiPaperAdapter(unittest.TestCase):
    def setUp(self):
        self.broker = SbiPaperAdapter()

    def test_order_history_is_recorded(self):
        self.broker.connect()

        order = OrderRequest("7203.T", OrderSide.BUY, 100)
        self.broker.place_order(order)

        history = self.broker.get_order_history()

        self.assertEqual(len(history), 1)
        self.assertTrue(history[0].is_accepted)

    def test_history_returns_copy(self):
        self.broker.connect()

        order = OrderRequest("7203.T", OrderSide.BUY, 100)
        self.broker.place_order(order)

        history = self.broker.get_order_history()
        history.clear()

        self.assertEqual(len(self.broker.get_order_history()), 1)


if __name__ == "__main__":
    unittest.main()
