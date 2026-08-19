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

    def execute_ibkr_paper_order(
        self,
        order: OrderRequest,
        *,
        order_intent_id: str,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.5,
    ):
        """IBKR Paper専用の非同期注文経路。

        BrokerAdapterの共通同期fill_order()は使わず、Phase 1で実装済みの
        place_order_and_await_fill()を1回だけ呼ぶ。タイムアウト、拒否、
        UNKNOWN、取消などを成功扱いせず、Filledを直接観測できた場合だけ
        Accountへ約定を反映する。

        Live用経路ではない。IBKR以外の既存同期経路は変更しない。
        """
        from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter

        if not isinstance(self._broker, IbkrBrokerAdapter):
            raise TypeError("IBKR Paper注文にはIbkrBrokerAdapterが必要です")

        if not self._broker.is_connected():
            raise RuntimeError("IBKRへ接続されていません")

        result = self._broker.place_order_and_await_fill(
            order,
            order_intent_id=order_intent_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

        if (
            not result.sent
            or not result.reached_terminal
            or result.last_known_status != "Filled"
            or result.order_id is None
            or result.filled_quantity <= 0
            or result.avg_fill_price is None
            or result.avg_fill_price <= 0
        ):
            return result

        filled_quantity = int(result.filled_quantity)
        if float(filled_quantity) != result.filled_quantity:
            raise RuntimeError("端数株の約定は現在のAccountモデルへ反映できません")

        fill = FillResult(
            order_id=str(result.order_id),
            symbol=order.symbol,
            side=order.side,
            quantity=filled_quantity,
            fill_price=result.avg_fill_price,
        )
        self._account.apply_fill(fill)
        return result

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
