import unittest

from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.portfolio.portfolio import Portfolio


class TestPortfolio(unittest.TestCase):
    def test_partial_sale_records_profit(self):
        portfolio = Portfolio()

        portfolio.apply_fill(
            FillResult(
                "1", "7203.T", OrderSide.BUY, 100, 3000.0
            )
        )
        portfolio.apply_fill(
            FillResult(
                "2", "7203.T", OrderSide.SELL, 40, 3200.0
            )
        )

        position = portfolio.get_position("7203.T")

        self.assertIsNotNone(position)
        self.assertEqual(position.quantity, 60)
        self.assertEqual(position.average_price, 3000.0)
        self.assertEqual(portfolio.realized_pnl, 8000.0)

    def test_sale_records_loss(self):
        portfolio = Portfolio()

        portfolio.apply_fill(
            FillResult(
                "1", "7203.T", OrderSide.BUY, 100, 3000.0
            )
        )
        portfolio.apply_fill(
            FillResult(
                "2", "7203.T", OrderSide.SELL, 20, 2800.0
            )
        )

        self.assertEqual(portfolio.realized_pnl, -4000.0)

    def test_multiple_sales_accumulate_realized_pnl(self):
        portfolio = Portfolio()

        portfolio.apply_fill(
            FillResult(
                "1", "7203.T", OrderSide.BUY, 100, 3000.0
            )
        )
        portfolio.apply_fill(
            FillResult(
                "2", "7203.T", OrderSide.SELL, 40, 3200.0
            )
        )
        portfolio.apply_fill(
            FillResult(
                "3", "7203.T", OrderSide.SELL, 60, 3100.0
            )
        )

        self.assertIsNone(portfolio.get_position("7203.T"))
        self.assertEqual(portfolio.realized_pnl, 14000.0)

    def test_sell_more_than_holding_is_rejected(self):
        portfolio = Portfolio()

        portfolio.apply_fill(
            FillResult(
                "1", "7203.T", OrderSide.BUY, 100, 3000.0
            )
        )

        with self.assertRaises(ValueError):
            portfolio.apply_fill(
                FillResult(
                    "2", "7203.T", OrderSide.SELL, 101, 3200.0
                )
            )

        self.assertEqual(portfolio.realized_pnl, 0.0)


if __name__ == "__main__":
    unittest.main()
