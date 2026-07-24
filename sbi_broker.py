from logging import Logger
from typing import Any

from execution import BrokerClient, Order
from stability import create_daily_logger


class SbiBroker(BrokerClient):
    """SBI証券接続を将来追加するためのブローカー土台。"""

    def __init__(self, logger: Logger | None = None, log_dir: str = "results") -> None:
        self.logger = logger or create_daily_logger("sbi_broker", log_dir=log_dir)

    def authenticate(self) -> None:
        """SBI証券への認証処理。実装前のため安全に停止する。"""
        raise NotImplementedError("SBI証券の認証処理は未実装です。")

    def submit_order(self, order: Order, available_cash: float) -> bool:
        """SBI証券への注文送信。実装前のため安全に停止する。"""
        raise NotImplementedError("SBI証券の注文送信は未実装です。")

    def cancel_order(self, order_id: str) -> bool:
        """SBI証券の注文取消。実装前のため安全に停止する。"""
        raise NotImplementedError("SBI証券の注文取消は未実装です。")

    def get_balance(self) -> dict[str, Any]:
        """SBI証券口座の残高取得。実装前のため安全に停止する。"""
        raise NotImplementedError("SBI証券の残高取得は未実装です。")

    def get_positions(self) -> list[dict[str, Any]]:
        """SBI証券口座の保有銘柄取得。実装前のため安全に停止する。"""
        raise NotImplementedError("SBI証券の保有銘柄取得は未実装です。")
