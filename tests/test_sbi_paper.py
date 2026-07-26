import unittest

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter


class TestSbiPaperAdapter(unittest.TestCase):
    def setUp(self):
        self.broker = SbiPaperAdapter()

    def test_order_rejected_when_not_connected(self):
        order = OrderRequest("7203.T", OrderSide.BUY, 100)
        result = self.broker.place_order(order)

        self.assertFalse(result.is_accepted)

    def test_order_accepted_when_connected(self):
        self.broker.connect()

        order = OrderRequest("7203.T", OrderSide.BUY, 100)
        result = self.broker.place_order(order)

        self.assertTrue(result.is_accepted)
        self.assertTrue(result.order_id.startswith("PAPER-"))


if __name__ == "__main__":
    unittest.main()
