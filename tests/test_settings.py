import unittest

from ai_asset_platform.core.settings import SETTINGS, PlatformSettings


class TestPlatformSettings(unittest.TestCase):
    def test_default_settings(self):
        self.assertIsInstance(SETTINGS, PlatformSettings)
        self.assertEqual(SETTINGS.system_name, "AI Asset Platform")
        self.assertEqual(SETTINGS.system_version, "3.1-dev")
        self.assertEqual(SETTINGS.run_mode, "DEVELOPMENT")
        self.assertTrue(SETTINGS.enable_ai)
        self.assertTrue(SETTINGS.enable_paper_trading)
        self.assertIn("JP_STOCK", SETTINGS.supported_markets)
        self.assertIn("SBI", SETTINGS.supported_brokers)

    def test_settings_are_immutable(self):
        with self.assertRaises(Exception):
            SETTINGS.run_mode = "LIVE"


if __name__ == "__main__":
    unittest.main()
