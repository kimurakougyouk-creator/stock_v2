"""
Broker Manager
"""

from ai_asset_platform.core.settings import SETTINGS


class BrokerManager:
    def __init__(self):
        self.available = list(SETTINGS.supported_brokers)

    def get_default(self):
        return self.available[0]

    def get_all(self):
        return self.available.copy()


if __name__ == "__main__":
    manager = BrokerManager()

    print("=" * 40)
    print("Default Broker :", manager.get_default())
    print("Supported      :", ", ".join(manager.get_all()))
    print("=" * 40)
