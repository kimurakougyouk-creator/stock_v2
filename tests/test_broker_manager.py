import unittest

from ai_asset_platform.brokers.manager import BrokerManager


class TestBrokerManager(unittest.TestCase):
    def setUp(self):
        self.manager = BrokerManager()

    def test_default_broker(self):
        self.assertEqual(self.manager.get_default(), "SBI")

    def test_supported_brokers(self):
        self.assertIn("SBI", self.manager.get_all())

    def test_get_all_returns_copy(self):
        brokers = self.manager.get_all()
        brokers.append("TEST")

        self.assertNotIn("TEST", self.manager.get_all())


if __name__ == "__main__":
    unittest.main()
