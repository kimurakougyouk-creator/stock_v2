import unittest
from unittest.mock import patch

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.manager import BrokerManager
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter
from ai_asset_platform.core.settings import PlatformSettings


class TestBrokerManager(unittest.TestCase):
    def setUp(self):
        self.manager = BrokerManager()

    def test_default_broker(self):
        self.assertEqual(self.manager.get_default(), "SBI")

    def test_supported_brokers(self):
        self.assertIn("SBI", self.manager.get_all())
        self.assertNotIn("IBKR_PAPER", self.manager.get_all())

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

    def test_ibkr_paper_is_disabled_by_default(self):
        with self.assertRaisesRegex(ValueError, "明示的に有効化"):
            self.manager.create_adapter("IBKR_PAPER")

    def test_ibkr_paper_requires_explicit_name_and_opt_in(self):
        enabled = PlatformSettings(enable_ibkr_paper=True)
        with patch("ai_asset_platform.brokers.manager.SETTINGS", enabled):
            manager = BrokerManager()
            adapter = manager.create_adapter("IBKR_PAPER")

        self.assertIsInstance(adapter, IbkrBrokerAdapter)
        self.assertEqual(manager.get_default(), "SBI")
        self.assertNotIn("IBKR_PAPER", manager.get_all())

    def test_bare_ibkr_name_is_always_rejected(self):
        enabled = PlatformSettings(enable_ibkr_paper=True)
        with patch("ai_asset_platform.brokers.manager.SETTINGS", enabled):
            manager = BrokerManager()
            with self.assertRaises(ValueError):
                manager.create_adapter("IBKR")

    def test_ibkr_live_name_is_always_rejected(self):
        enabled = PlatformSettings(enable_ibkr_paper=True)
        with patch("ai_asset_platform.brokers.manager.SETTINGS", enabled):
            manager = BrokerManager()
            with self.assertRaises(ValueError):
                manager.create_adapter("IBKR_LIVE")

    def test_unsupported_broker(self):
        with self.assertRaises(ValueError):
            self.manager.create_adapter("UNKNOWN")


if __name__ == "__main__":
    unittest.main()
