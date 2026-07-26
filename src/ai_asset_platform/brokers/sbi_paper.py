"""
SBI証券の模擬接続アダプター

実口座・実注文には接続しません。
"""

from ai_asset_platform.brokers.base import BrokerAdapter


class SbiPaperAdapter(BrokerAdapter):
    def __init__(self) -> None:
        self._connected = False

    @property
    def name(self) -> str:
        return "SBI_PAPER"

    def connect(self) -> bool:
        self._connected = True
        return self._connected

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False


if __name__ == "__main__":
    broker = SbiPaperAdapter()

    print("=" * 40)
    print("Broker    :", broker.name)
    print("Connected :", broker.is_connected())
    print("Connect   :", broker.connect())
    print("Connected :", broker.is_connected())
    broker.disconnect()
    print("Connected :", broker.is_connected())
    print("=" * 40)
