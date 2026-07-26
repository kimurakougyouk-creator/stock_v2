import unittest

from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.portfolio.portfolio import Portfolio


class TestPortfolio(unittest.TestCase):

    def test_buy_then_sell(self):
        pf = Portfolio()

        pf.apply_fill(FillResult(
            "1", "7203.T", OrderSide.BUY, 100, 3000.0
        ))

        pf.apply_fill(FillResult(
            "2", "7203.T", OrderSide.SELL, 40, 3200.0
        ))

        pos = pf.get_position("7203.T")

        self.assertEqual(pos.quantity, 60)
        self.assertEqual(pos.average_price, 3000.0)

    def test_sell_all(self):
        pf = Portfolio()

        pf.apply_fill(FillResult(
            "1", "7203.T", OrderSide.BUY, 100, 3000.0
        ))

        pf.apply_fill(FillResult(
            "2", "7203.T", OrderSide.SELL, 100, 3200.0
        ))

        self.assertIsNone(pf.get_position("7203.T"))

    def test_sell_too_many(self):
        pf = Portfolio()

        pf.apply_fill(FillResult(
            "1", "7203.T", OrderSide.BUY, 100, 3000.0
        ))

        with self.assertRaises(ValueError):
            pf.apply_fill(FillResult(
                "2", "7203.T", OrderSide.SELL, 101, 3200.0
            ))


if __name__ == "__main__":
    unittest.main()
