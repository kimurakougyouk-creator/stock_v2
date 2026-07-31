from ai_asset_platform.execution.order_request import OrderRequest


def validate_order_request(order: OrderRequest) -> bool:
    if order.quantity <= 0:
        return False

    if order.action not in {"BUY", "SELL"}:
        return False

    return True
