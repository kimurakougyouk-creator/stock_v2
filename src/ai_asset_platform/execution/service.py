"""
注文、約定、口座反映をまとめて安全に実行するサービス
"""

from dataclasses import dataclass
from typing import Callable
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.account import Account
from ai_asset_platform.brokers.orders import (
    FillResult,
    OrderRequest,
    OrderSide,
    OrderType,
)
from ai_asset_platform.brokers.base import BrokerAdapter
from ai_asset_platform.execution.confirmed_fill_evidence import (
    confirmed_fill_from_broker_result,
)


@dataclass(frozen=True)
class RiskGateResult:
    allowed: bool
    reason: str = ""


RiskGate = Callable[[OrderRequest], RiskGateResult]


class ExecutionService:
    def __init__(
        self,
        broker: BrokerAdapter,
        account: Account,
        risk_gate: RiskGate | None = None,
    ) -> None:
        self._broker = broker
        self._account = account
        self._risk_gate = risk_gate

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
        instrument: InstrumentSpec | None = None,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.5,
        apply_account_fill: bool = True,
    ):
        """IBKR Paper専用の非同期注文経路。

        共有Risk Gateを送信前に必ず評価する。ブロック時はbrokerの
        place_order_and_await_fill()へ到達しない。

        ``instrument`` は市場・通貨を含む明示的なContract情報。省略時は
        既存のUS STOCK既定値を維持するが、移行済みsignal経路は必ず渡す。

        ``apply_account_fill=False`` は、移行期間中に legacy の永続取引履歴を
        唯一の会計状態として使う呼び出し側専用。IBKRの送信・Filled判定には
        影響せず、メモリAccountへの二重反映だけを止める。
        """
        from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter

        if not isinstance(self._broker, IbkrBrokerAdapter):
            raise TypeError("IBKR Paper注文にはIbkrBrokerAdapterが必要です")

        if not self._broker.is_connected():
            raise RuntimeError("IBKRへ接続されていません")

        self._check_risk_gate(order)

        result = self._broker.place_order_and_await_fill(
            order,
            order_intent_id=order_intent_id,
            instrument=instrument,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

        # The current Account model is integer-quantity only. Preserve the
        # existing fail-closed behavior even when an explicit terminal Filled
        # callback reports a fractional quantity that is too small to satisfy
        # the requested integer order. Silently returning/truncating it would
        # hide an accounting-model incompatibility.
        if str(getattr(result, "last_known_status", "") or "") == "Filled":
            observed_quantity = float(getattr(result, "filled_quantity", 0.0) or 0.0)
            if observed_quantity > 0 and float(int(observed_quantity)) != observed_quantity:
                raise RuntimeError("端数株の約定は現在のAccountモデルへ反映できません")

        confirmed = confirmed_fill_from_broker_result(result, order.quantity)
        if confirmed is None or result.order_id is None:
            return result

        confirmed_quantity, confirmed_price = confirmed
        filled_quantity = int(confirmed_quantity)
        if float(filled_quantity) != confirmed_quantity:
            raise RuntimeError("端数株の約定は現在のAccountモデルへ反映できません")

        if apply_account_fill:
            fill = FillResult(
                order_id=str(result.order_id),
                symbol=order.symbol,
                side=order.side,
                quantity=filled_quantity,
                fill_price=confirmed_price,
            )
            self._account.apply_fill(fill)
        return result

    def _check_risk_gate(self, order: OrderRequest) -> None:
        if self._risk_gate is None:
            return

        decision = self._risk_gate(order)
        if not isinstance(decision, RiskGateResult):
            raise TypeError("risk_gateはRiskGateResultを返してください")

        if not decision.allowed:
            reason = decision.reason or "Risk Gateにより注文が拒否されました"
            raise RuntimeError(reason)

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
