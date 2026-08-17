import unittest

from ai_asset_platform.brokers.base import BrokerAdapter


class TestBrokerAdapter(unittest.TestCase):
    def test_abstract_class_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            BrokerAdapter()


if __name__ == "__main__":
    unittest.main()
