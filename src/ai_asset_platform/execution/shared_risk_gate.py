"""Shared fail-closed pre-send risk gate for migrated execution paths.

This module deliberately reuses the verified legacy paper ledger as the current
source of daily-order/loss/cooldown state while the execution stack is migrated.
It does not enable any broker or Live Trading capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.core.settings import PlatformSettings, SETTINGS
from ai_asset_platform.execution.service import RiskGateResult


@dataclass(frozen=True)
class LegacyRiskSnapshot:
    daily_buy_orders: int
    daily_sell_orders: int
    daily_realized_pnl: float
    consecutive_losses: int
    repurchase_cooldown_minutes: int


SnapshotProvider = Callable[[OrderRequest, PlatformSettings], LegacyRiskSnapshot]


def load_legacy_risk_snapshot(
    order: OrderRequest,
    settings: PlatformSettings = SETTINGS,
) -> LegacyRiskSnapshot:
    """Read safety state from the existing durable paper-order ledger."""
    from order_manager import (
        calculate_consecutive_losses,
        calculate_daily_buy_order_count,
        calculate_daily_realized_pnl,
        calculate_daily_sell_order_count,
        calculate_repurchase_cooldown_remaining_minutes,
    )

    cooldown = 0
    if order.side is OrderSide.BUY:
        cooldown = calculate_repurchase_cooldown_remaining_minutes(
            order.symbol,
            settings.repurchase_cooldown_minutes,
        )

    return LegacyRiskSnapshot(
        daily_buy_orders=calculate_daily_buy_order_count(),
        daily_sell_orders=calculate_daily_sell_order_count(),
        daily_realized_pnl=calculate_daily_realized_pnl(),
        consecutive_losses=calculate_consecutive_losses(),
        repurchase_cooldown_minutes=cooldown,
    )


def build_shared_risk_gate(
    *,
    settings: PlatformSettings = SETTINGS,
    snapshot_provider: SnapshotProvider = load_legacy_risk_snapshot,
):
    """Return a fail-closed RiskGate compatible with ExecutionService.

    The checks here are intentionally limited to controls that can be evaluated
    from OrderRequest plus durable legacy state without guessing a market price.
    Price-dependent allocation/notional checks remain outside this gate until a
    priced order context is introduced.
    """

    def gate(order: OrderRequest) -> RiskGateResult:
        if settings.emergency_stop:
            return RiskGateResult(False, "緊急停止が有効なため注文を拒否しました")

        if not settings.enable_paper_trading:
            return RiskGateResult(False, "Paper Tradingが無効なため注文を拒否しました")

        if order.quantity <= 0:
            return RiskGateResult(False, "注文数量は1以上である必要があります")

        if order.quantity > settings.max_order_shares:
            return RiskGateResult(False, "1注文の最大株数を超えています")

        try:
            snapshot = snapshot_provider(order, settings)
        except Exception as exc:
            return RiskGateResult(False, f"Risk状態を確認できないため注文を拒否しました: {exc}")

        if snapshot.daily_realized_pnl <= -abs(settings.daily_loss_limit_yen):
            return RiskGateResult(False, "1日の損失上限に到達しています")

        if snapshot.consecutive_losses >= settings.max_consecutive_losses:
            return RiskGateResult(False, "連続損失上限に到達しています")

        if order.side is OrderSide.BUY:
            if snapshot.daily_buy_orders >= settings.max_daily_buy_orders:
                return RiskGateResult(False, "1日のBUY注文上限に到達しています")
            if snapshot.repurchase_cooldown_minutes > 0:
                return RiskGateResult(
                    False,
                    f"再購入クールダウン中です（残り{snapshot.repurchase_cooldown_minutes}分）",
                )
        elif order.side is OrderSide.SELL:
            if snapshot.daily_sell_orders >= settings.max_daily_sell_orders:
                return RiskGateResult(False, "1日のSELL注文上限に到達しています")
        else:
            return RiskGateResult(False, "未対応の注文サイドです")

        return RiskGateResult(True, "shared risk gate passed")

    return gate
