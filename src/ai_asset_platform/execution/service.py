"""
注文、約定、口座反映をまとめて安全に実行するサービス
"""

from ai_asset_platform.account import Account
from ai_asset_platform.brokers.orders import (
    FillResult,
    OrderRequest,
    OrderSide,
    OrderType,
)
from ai_asset_platform.brokers.base import BrokerAdapter


class ExecutionService:
    def __init__(
        self,
        broker: BrokerAdapter,
        account: Account,
    ) -> None:
        self._broker = broker
        self._account = account

    @property
    def broker(self) -> BrokerAdapter:
        return self._broker

    @property
    def account(self) -> Account:
        return self._account

    def execute_market_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
    ) -> FillResult:
        """
        成行注文を模擬約定し、口座へ自動反映する。
        """

        if not self._broker.is_connected():
            raise RuntimeError("証券会社へ接続されていません")

        if price <= 0:
            raise ValueError("約定価格は0より大きくしてください")

        self._validate_account(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
        )

        order = OrderRequest(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
        )

        fill = self._broker.fill_order(
            order=order,
            price=price,
        )

        self._account.apply_fill(fill)

        return fill

    def _validate_account(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
    ) -> None:
        if quantity <= 0:
            raise ValueError("注文数量は1以上にしてください")

        if side is OrderSide.BUY:
            required_cash = quantity * price

            if required_cash > self._account.buying_power:
                raise ValueError("買付可能額が不足しています")

            return

        if side is OrderSide.SELL:
            position = self._account.portfolio.get_position(symbol)

            if position is None:
                raise ValueError("売却できる保有株がありません")

            if quantity > position.quantity:
                raise ValueError("保有数量を超えて売却できません")

            return

        raise ValueError(f"未対応の注文種別です: {side}")
