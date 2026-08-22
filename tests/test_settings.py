import unittest
from unittest.mock import patch

from ai_asset_platform.core.settings import SETTINGS, PlatformSettings


class TestPlatformSettings(unittest.TestCase):
    def test_default_settings(self):
        self.assertIsInstance(SETTINGS, PlatformSettings)
        self.assertEqual(SETTINGS.system_name, "AI Asset Platform")
        self.assertEqual(SETTINGS.system_version, "3.1-dev")
        self.assertEqual(SETTINGS.run_mode, "DEVELOPMENT")
        self.assertTrue(SETTINGS.enable_ai)
        self.assertFalse(SETTINGS.emergency_stop)
        self.assertTrue(SETTINGS.enable_paper_trading)
        self.assertFalse(SETTINGS.enable_live_trading)
        self.assertIn("JP_STOCK", SETTINGS.supported_markets)
        self.assertIn("US_STOCK", SETTINGS.supported_markets)
        self.assertIn("US_ETF", SETTINGS.supported_markets)
        self.assertNotIn("US_OVERNIGHT", SETTINGS.supported_markets)
        self.assertIn("SBI", SETTINGS.supported_brokers)
        self.assertIn("IBKR", SETTINGS.supported_brokers)

    def test_ibkr_paper_defaults_off_without_explicit_opt_in(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = PlatformSettings()
        self.assertFalse(settings.enable_ibkr_paper)

    def test_ibkr_paper_can_be_explicitly_enabled_for_one_process(self):
        with patch.dict("os.environ", {"AI_ASSET_ENABLE_IBKR_PAPER": "true"}, clear=True):
            settings = PlatformSettings()
        self.assertTrue(settings.enable_ibkr_paper)

    def test_invalid_ibkr_paper_env_value_fails_closed(self):
        with patch.dict("os.environ", {"AI_ASSET_ENABLE_IBKR_PAPER": "unexpected"}, clear=True):
            settings = PlatformSettings()
        self.assertFalse(settings.enable_ibkr_paper)

    def test_settings_are_immutable(self):
        with self.assertRaises(Exception):
            SETTINGS.run_mode = "LIVE"


if __name__ == "__main__":
    unittest.main()


class TestLiveTradingSafetyLock(unittest.TestCase):
    def test_development_and_disabled_is_locked(self):
        settings = PlatformSettings(
            run_mode="DEVELOPMENT",
            enable_live_trading=False,
        )

        self.assertFalse(settings.live_trading_unlocked)

    def test_live_and_disabled_is_locked(self):
        settings = PlatformSettings(
            run_mode="LIVE",
            enable_live_trading=False,
        )

        self.assertFalse(settings.live_trading_unlocked)

    def test_development_and_enabled_is_locked(self):
        settings = PlatformSettings(
            run_mode="DEVELOPMENT",
            enable_live_trading=True,
        )

        self.assertFalse(settings.live_trading_unlocked)

    def test_live_and_enabled_is_unlocked(self):
        settings = PlatformSettings(
            run_mode="LIVE",
            enable_live_trading=True,
        )

        self.assertTrue(settings.live_trading_unlocked)

    def test_emergency_stop_keeps_live_trading_locked(self):
        settings = PlatformSettings(
            run_mode="LIVE",
            enable_live_trading=True,
            emergency_stop=True,
        )

        self.assertFalse(settings.live_trading_unlocked)
