import unittest

from ai_asset_platform.portfolio.position import Position


class TestPosition(unittest.TestCase):
    def test_cost(self):
        p = Position("7203.T", 100, 3000.0)
        self.assertEqual(p.cost, 300000.0)

    def test_invalid_quantity(self):
        with self.assertRaises(ValueError):
            Position("7203.T", 0, 3000.0)

    def test_invalid_price(self):
        with self.assertRaises(ValueError):
            Position("7203.T", 100, 0)


if __name__ == "__main__":
    unittest.main()
