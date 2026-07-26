import unittest

from ai_asset_platform.portfolio.position import Position
from ai_asset_platform.portfolio.portfolio import Portfolio


class TestPortfolio(unittest.TestCase):

    def test_add_position(self):
        pf = Portfolio()
        pf.add_position(Position("7203.T", 100, 3000))

        self.assertIsNotNone(pf.get_position("7203.T"))

    def test_total_cost(self):
        pf = Portfolio()

        pf.add_position(Position("7203.T", 100, 3000))
        pf.add_position(Position("6758.T", 50, 2000))

        self.assertEqual(pf.total_cost, 400000)

    def test_get_all_positions(self):
        pf = Portfolio()

        pf.add_position(Position("7203.T", 100, 3000))
        pf.add_position(Position("6758.T", 50, 2000))

        self.assertEqual(len(pf.get_all_positions()), 2)


if __name__ == "__main__":
    unittest.main()
