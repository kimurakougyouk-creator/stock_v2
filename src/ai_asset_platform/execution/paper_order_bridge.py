from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.execution.order_candidate import OrderCandidate
from ai_asset_platform.execution.service import ExecutionService


def execute_paper_order(
    candidate: OrderCandidate,
    execution_service: ExecutionService,
    price: float,
) -> FillResult:
    """
    OrderCandidate を既存の ExecutionService へ渡す互換レイヤー。

    Paper Trading の実行経路を ExecutionService 側へ
    段階的に一本化するための入口として使用する。
    """

    try:
        side = OrderSide(candidate.action)
    except ValueError as exc:
        raise ValueError(
            f"未対応の売買アクションです: {candidate.action}"
        ) from exc

    return execution_service.execute_market_order(
        symbol=candidate.symbol,
        side=side,
        quantity=candidate.quantity,
        price=price,
    )
