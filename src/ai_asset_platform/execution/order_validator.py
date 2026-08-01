from ai_asset_platform.brokers.orders import OrderRequest


def validate_order_request(order: OrderRequest) -> bool:
    return bool(order.symbol.strip()) and order.quantity > 0
