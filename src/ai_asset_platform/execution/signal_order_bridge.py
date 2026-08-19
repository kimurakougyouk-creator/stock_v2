"""signal_runnerの確定売買判断をExecutionServiceへ安全に橋渡しする。"""

from dataclasses import dataclass

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.service import ExecutionService


@dataclass(frozen=True)
class SignalExecutionResult:
    attempted: bool
    reason: str
    broker_result: object | None = None


def execute_signal_via_ibkr_paper(
    *,
    service: ExecutionService,
    ticker: str,
    signal: str,
    shares: int,
    order_intent_id: str,
    apply_account_fill: bool = True,
) -> SignalExecutionResult:
    """確定済みBUY/SELLをIBKR Paper経路へ渡す。

    二重opt-in: enable_paper_trading と enable_ibkr_paper の両方がTrueで、
    かつBUY/SELL・正数量の場合だけExecutionServiceへ到達する。
    Live経路は持たない。
    """
    if not SETTINGS.enable_paper_trading:
        return SignalExecutionResult(False, "paper trading disabled")

    if not SETTINGS.enable_ibkr_paper:
        return SignalExecutionResult(False, "IBKR Paper disabled")

    normalized = str(signal).upper()
    if normalized not in {"BUY", "SELL"}:
        return SignalExecutionResult(False, "non-actionable signal")

    if int(shares) <= 0:
        return SignalExecutionResult(False, "invalid shares")

    side = OrderSide.BUY if normalized == "BUY" else OrderSide.SELL
    order = OrderRequest(
        symbol=ticker,
        side=side,
        quantity=int(shares),
        order_type=OrderType.MARKET,
    )

    result = service.execute_ibkr_paper_order(
        order,
        order_intent_id=order_intent_id,
        apply_account_fill=apply_account_fill,
    )
    return SignalExecutionResult(True, "submitted to IBKR Paper execution service", result)
