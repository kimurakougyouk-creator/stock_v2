"""既存order_managerの安全判定をExecutionService Risk Gateへ接続する。"""

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.service import RiskGateResult


def legacy_order_manager_risk_gate(order: OrderRequest) -> RiskGateResult:
    """既存のPaper注文履歴を使い、IBKR送信前に安全上限を判定する。

    このアダプター自身は注文送信・取消・ファイル書込みを行わない。
    """
    import order_manager

    if SETTINGS.emergency_stop:
        return RiskGateResult(False, "emergency stop")

    if order.quantity <= 0:
        return RiskGateResult(False, "invalid quantity")

    if order.quantity > SETTINGS.max_order_shares:
        return RiskGateResult(False, "max order shares")

    if order.side is OrderSide.BUY:
        if order_manager.calculate_daily_buy_order_count() >= SETTINGS.max_daily_buy_orders:
            return RiskGateResult(False, "daily buy order limit")

        remaining = order_manager.calculate_repurchase_cooldown_remaining_minutes(
            order.symbol,
            SETTINGS.repurchase_cooldown_minutes,
        )
        if remaining > 0:
            return RiskGateResult(False, "repurchase cooldown")

    elif order.side is OrderSide.SELL:
        if order_manager.calculate_daily_sell_order_count() >= SETTINGS.max_daily_sell_orders:
            return RiskGateResult(False, "daily sell order limit")

    if order_manager.calculate_daily_trading_amount() >= SETTINGS.max_daily_trading_amount_yen:
        return RiskGateResult(False, "daily trading amount limit")

    if order_manager.calculate_daily_realized_pnl() <= -SETTINGS.daily_loss_limit_yen:
        return RiskGateResult(False, "daily loss limit")

    if order_manager.calculate_consecutive_losses() >= SETTINGS.max_consecutive_losses:
        return RiskGateResult(False, "consecutive loss limit")

    return RiskGateResult(True)
