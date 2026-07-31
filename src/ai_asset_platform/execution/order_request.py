from dataclasses import dataclass

from ai_asset_platform.execution.order_candidate import OrderCandidate


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    action: str
    quantity: int


def create_order_request(
    candidate: OrderCandidate,
) -> OrderRequest:
    return OrderRequest(
        symbol=candidate.symbol,
        action=candidate.action,
        quantity=candidate.quantity,
    )
