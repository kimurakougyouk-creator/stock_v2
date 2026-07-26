import unittest

from ai_asset_platform.brokers.base import BrokerAdapter
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter


class TestSbiPaperAdapter(unittest.TestCase):
    def setUp(self):
        self.broker = SbiPaperAdapter()

    def test_implements_broker_adapter(self):
        self.assertIsInstance(self.broker, BrokerAdapter)

    def test_broker_name(self):
        self.assertEqual(self.broker.name, "SBI_PAPER")

    def test_connect_and_disconnect(self):
        self.assertFalse(self.broker.is_connected())
        self.assertTrue(self.broker.connect())
        self.assertTrue(self.broker.is_connected())

        self.broker.disconnect()

        self.assertFalse(self.broker.is_connected())


if __name__ == "__main__":
    unittest.main()
