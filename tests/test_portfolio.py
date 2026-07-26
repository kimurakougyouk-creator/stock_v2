import unittest

from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.portfolio.portfolio import Portfolio


class TestPortfolio(unittest.TestCase):

    def test_apply_fill(self):
        pf = Portfolio()

        fill = FillResult(
            order_id="PAPER-000001",
            symbol="7203.T",
            side=OrderSide.BUY,
            quantity=100,
            fill_price=3000.0,
        )

        pf.apply_fill(fill)

        pos = pf.get_position("7203.T")

        self.assertEqual(pos.quantity, 100)
        self.assertEqual(pos.average_price, 3000.0)
        self.assertEqual(pf.total_cost, 300000.0)


if __name__ == "__main__":
    unittest.main()
