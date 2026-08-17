from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.execution.order_candidate import OrderCandidate
from ai_asset_platform.execution.service import ExecutionService


def execute_order_candidate(
    candidate: OrderCandidate,
    execution_service: ExecutionService,
    price: float,
) -> FillResult:
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
