"""
証券会社アダプターの共通インターフェース
"""

from abc import ABC, abstractmethod

from ai_asset_platform.brokers.orders import FillResult, OrderRequest


class BrokerAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """証券会社名を返す。"""

    @abstractmethod
    def connect(self) -> bool:
        """証券会社へ接続する。"""

    @abstractmethod
    def is_connected(self) -> bool:
        """接続状態を返す。"""

    @abstractmethod
    def disconnect(self) -> None:
        """証券会社との接続を終了する。"""

    @abstractmethod
    def place_order(self, order: OrderRequest):
        """注文を証券会社へ送る。"""

    @abstractmethod
    def fill_order(
        self,
        order: OrderRequest,
        price: float,
    ) -> FillResult:
        """注文を約定させ、その結果を返す。"""
