import unittest

from ai_asset_platform.brokers.manager import BrokerManager
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter


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

    def test_create_default_adapter(self):
        adapter = self.manager.create_adapter()
        self.assertIsInstance(adapter, SbiPaperAdapter)

    def test_create_sbi_paper_adapter(self):
        adapter = self.manager.create_adapter("SBI_PAPER")
        self.assertIsInstance(adapter, SbiPaperAdapter)

    def test_unsupported_broker(self):
        with self.assertRaises(ValueError):
            self.manager.create_adapter("UNKNOWN")


if __name__ == "__main__":
    unittest.main()
