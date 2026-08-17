import unittest

from ai_asset_platform.account.account import Account
from ai_asset_platform.brokers.orders import FillResult, OrderSide


class TestAccountInitialization(unittest.TestCase):
    def test_initial_cash_is_stored(self):
        account = Account(initial_cash=1_000_000.0)

        self.assertEqual(account.cash, 1_000_000.0)
        self.assertEqual(account.buying_power, 1_000_000.0)

    def test_negative_initial_cash_is_rejected(self):
        with self.assertRaises(ValueError):
            Account(initial_cash=-1.0)


class TestAccountTrading(unittest.TestCase):
    def test_buy_reduces_cash_and_creates_position(self):
        account = Account(initial_cash=1_000_000.0)

        account.apply_fill(
            FillResult(
                order_id="1",
                symbol="7203.T",
                side=OrderSide.BUY,
                quantity=100,
                fill_price=3000.0,
            )
        )

        position = account.portfolio.get_position("7203.T")

        self.assertEqual(account.cash, 700_000.0)
        self.assertIsNotNone(position)
        self.assertEqual(position.quantity, 100)
        self.assertEqual(position.average_price, 3000.0)

    def test_insufficient_cash_rejects_buy(self):
        account = Account(initial_cash=100_000.0)

        with self.assertRaises(ValueError):
            account.apply_fill(
                FillResult(
                    order_id="1",
                    symbol="7203.T",
                    side=OrderSide.BUY,
                    quantity=100,
                    fill_price=3000.0,
                )
            )

        self.assertEqual(account.cash, 100_000.0)
        self.assertIsNone(
            account.portfolio.get_position("7203.T")
        )

    def test_sell_increases_cash_and_reduces_position(self):
        account = Account(initial_cash=1_000_000.0)

        account.apply_fill(
            FillResult(
                order_id="1",
                symbol="7203.T",
                side=OrderSide.BUY,
                quantity=100,
                fill_price=3000.0,
            )
        )
        account.apply_fill(
            FillResult(
                order_id="2",
                symbol="7203.T",
                side=OrderSide.SELL,
                quantity=40,
                fill_price=3200.0,
            )
        )

        position = account.portfolio.get_position("7203.T")

        self.assertEqual(account.cash, 828_000.0)
        self.assertIsNotNone(position)
        self.assertEqual(position.quantity, 60)
        self.assertEqual(
            account.portfolio.realized_pnl,
            8000.0,
        )

    def test_invalid_sell_does_not_change_cash(self):
        account = Account(initial_cash=1_000_000.0)

        with self.assertRaises(ValueError):
            account.apply_fill(
                FillResult(
                    order_id="1",
                    symbol="7203.T",
                    side=OrderSide.SELL,
                    quantity=1,
                    fill_price=3000.0,
                )
            )

        self.assertEqual(account.cash, 1_000_000.0)


class TestAccountSummary(unittest.TestCase):
    def test_summary_combines_cash_and_portfolio(self):
        account = Account(initial_cash=1_000_000.0)

        account.apply_fill(
            FillResult(
                order_id="1",
                symbol="7203.T",
                side=OrderSide.BUY,
                quantity=100,
                fill_price=3000.0,
            )
        )

        summary = account.get_summary(
            market_prices={"7203.T": 3200.0}
        )

        self.assertEqual(summary["cash"], 700_000.0)
        self.assertEqual(summary["holdings"], 320_000.0)
        self.assertEqual(summary["total_assets"], 1_020_000.0)
        self.assertEqual(summary["realized_pnl"], 0.0)
        self.assertEqual(summary["unrealized_pnl"], 20_000.0)


if __name__ == "__main__":
    unittest.main()
