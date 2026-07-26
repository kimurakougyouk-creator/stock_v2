import unittest

from ai_asset_platform.brokers.orders import (
    OrderRequest,
    OrderSide,
    OrderType,
)


class TestOrderRequest(unittest.TestCase):
    def test_valid_market_buy_order(self):
        order = OrderRequest(
            symbol="7203.T",
            side=OrderSide.BUY,
            quantity=100,
        )

        self.assertEqual(order.symbol, "7203.T")
        self.assertEqual(order.side, OrderSide.BUY)
        self.assertEqual(order.quantity, 100)
        self.assertEqual(order.order_type, OrderType.MARKET)
        self.assertIsNone(order.limit_price)

    def test_valid_limit_sell_order(self):
        order = OrderRequest(
            symbol="7203.T",
            side=OrderSide.SELL,
            quantity=100,
            order_type=OrderType.LIMIT,
            limit_price=3000.0,
        )

        self.assertEqual(order.limit_price, 3000.0)

    def test_empty_symbol_is_rejected(self):
        with self.assertRaises(ValueError):
            OrderRequest(
                symbol=" ",
                side=OrderSide.BUY,
                quantity=100,
            )

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(ValueError):
            OrderRequest(
                symbol="7203.T",
                side=OrderSide.BUY,
                quantity=0,
            )

    def test_limit_order_requires_price(self):
        with self.assertRaises(ValueError):
            OrderRequest(
                symbol="7203.T",
                side=OrderSide.BUY,
                quantity=100,
                order_type=OrderType.LIMIT,
            )

    def test_market_order_rejects_limit_price(self):
        with self.assertRaises(ValueError):
            OrderRequest(
                symbol="7203.T",
                side=OrderSide.BUY,
                quantity=100,
                limit_price=3000.0,
            )


if __name__ == "__main__":
    unittest.main()


class TestOrderResult(unittest.TestCase):
    def test_accepted_order_result(self):
        from ai_asset_platform.brokers.orders import OrderResult, OrderStatus

        result = OrderResult(
            order_id="PAPER-0001",
            status=OrderStatus.ACCEPTED,
            message="模擬注文を受け付けました",
        )

        self.assertEqual(result.order_id, "PAPER-0001")
        self.assertTrue(result.is_accepted)

    def test_rejected_order_result(self):
        from ai_asset_platform.brokers.orders import OrderResult, OrderStatus

        result = OrderResult(
            order_id="PAPER-0002",
            status=OrderStatus.REJECTED,
            message="注文を拒否しました",
        )

        self.assertFalse(result.is_accepted)

    def test_empty_order_id_is_rejected(self):
        from ai_asset_platform.brokers.orders import OrderResult, OrderStatus

        with self.assertRaises(ValueError):
            OrderResult(
                order_id=" ",
                status=OrderStatus.REJECTED,
            )
