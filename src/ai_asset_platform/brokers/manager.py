"""
証券会社アダプター管理
"""

from ai_asset_platform.brokers.base import BrokerAdapter
from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.sbi_paper import SbiPaperAdapter
from ai_asset_platform.core.settings import SETTINGS


class BrokerManager:
    def __init__(self) -> None:
        self.available = list(SETTINGS.supported_brokers)

    def get_default(self) -> str:
        return self.available[0]

    def get_all(self) -> list[str]:
        return self.available.copy()

    def create_adapter(self, broker_name: str | None = None) -> BrokerAdapter:
        selected = broker_name or self.get_default()

        if selected in {"SBI", "SBI_PAPER"}:
            return SbiPaperAdapter()

        # IBKRは「IBKR_PAPER」の明示指定かつ設定opt-in時だけ生成する。
        # available/defaultには追加しないため、暗黙に選択されることはない。
        if selected == "IBKR_PAPER":
            if not SETTINGS.enable_ibkr_paper:
                raise ValueError("IBKR Paper Tradingは明示的に有効化されていません。")
            return IbkrBrokerAdapter()

        # "IBKR" / "IBKR_LIVE" 等は意図的に未対応のまま拒否する。
        raise ValueError(f"未対応の証券会社です: {selected}")


if __name__ == "__main__":
    manager = BrokerManager()
    broker = manager.create_adapter()

    print("=" * 40)
    print("Default Broker :", manager.get_default())
    print("Adapter        :", broker.name)
    print("Connected      :", broker.connect())
    broker.disconnect()
    print("=" * 40)
