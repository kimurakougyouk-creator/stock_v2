"""Shared fail-closed pre-send risk gate for migrated execution paths.

This module deliberately reuses the verified legacy paper ledger as the current
source of daily-order/loss/cooldown state while the execution stack is migrated.
It does not enable any broker or Live Trading capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
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
    daily_realized_pnl_currency_safe: bool = True


SnapshotProvider = Callable[[OrderRequest, PlatformSettings], LegacyRiskSnapshot]


def _today_ibkr_realized_pnl_currency_safe(records: list[dict]) -> bool:
    """Return whether today's IBKR realized-PnL rows can be treated as JPY.

    Only SELL fills dated today can contribute a realized PnL to today's loss
    total. Historical USD buys alone must not permanently block future BUYs.
    A today's IBKR SELL with missing/non-JPY currency makes the legacy JPY loss
    comparison unsafe because no explicit FX conversion exists yet.
    """
    today = date.today()
    for record in records:
        if str(record.get("mode", "")).strip().upper() != "IBKR_PAPER":
            continue
        if str(record.get("side", "")).strip().upper() != "SELL":
            continue
        try:
            created = datetime.fromisoformat(str(record["created_at"]))
        except (KeyError, TypeError, ValueError):
            # A malformed date means we cannot prove it is outside today's loss
            # calculation. Fail closed rather than silently ignore uncertainty.
            return False
        if created.date() != today:
            continue
        currency = str(record.get("currency", "")).strip().upper()
        if currency != "JPY":
            return False
    return True


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
        load_accounting_orders,
    )

    cooldown = 0
    if order.side is OrderSide.BUY:
        cooldown = calculate_repurchase_cooldown_remaining_minutes(
            order.symbol,
            settings.repurchase_cooldown_minutes,
        )

    accounting_orders = load_accounting_orders()
    return LegacyRiskSnapshot(
        daily_buy_orders=calculate_daily_buy_order_count(),
        daily_sell_orders=calculate_daily_sell_order_count(),
        daily_realized_pnl=calculate_daily_realized_pnl(),
        consecutive_losses=calculate_consecutive_losses(),
        repurchase_cooldown_minutes=cooldown,
        daily_realized_pnl_currency_safe=_today_ibkr_realized_pnl_currency_safe(
            accounting_orders
        ),
    )


def build_shared_risk_gate(
    *,
    settings: PlatformSettings = SETTINGS,
    snapshot_provider: SnapshotProvider = load_legacy_risk_snapshot,
):
    """Return a fail-closed RiskGate compatible with ExecutionService.

    Loss streak/daily-loss controls intentionally block new BUY exposure only,
    matching the legacy safety behavior so protective SELL exits remain possible.
    Disabled numeric limits (<= 0) are not treated as already exhausted.
    """

    def gate(order: OrderRequest) -> RiskGateResult:
        if settings.emergency_stop:
            return RiskGateResult(False, "緊急停止が有効なため注文を拒否しました")

        if not settings.enable_paper_trading:
            return RiskGateResult(False, "Paper Tradingが無効なため注文を拒否しました")

        if order.quantity <= 0:
            return RiskGateResult(False, "注文数量は1以上である必要があります")

        if settings.max_order_shares <= 0 or order.quantity > settings.max_order_shares:
            return RiskGateResult(False, "1注文の最大株数を超えています")

        try:
            snapshot = snapshot_provider(order, settings)
        except Exception as exc:
            return RiskGateResult(False, f"Risk状態を確認できないため注文を拒否しました: {exc}")

        if order.side is OrderSide.BUY:
            if (
                settings.daily_loss_limit_yen > 0
                and not snapshot.daily_realized_pnl_currency_safe
            ):
                return RiskGateResult(
                    False,
                    "IBKR損益を円換算できないため新規BUYを拒否しました",
                )
            if (
                settings.daily_loss_limit_yen > 0
                and snapshot.daily_realized_pnl <= -settings.daily_loss_limit_yen
            ):
                return RiskGateResult(False, "1日の損失上限に到達しています")
            if (
                settings.max_consecutive_losses > 0
                and snapshot.consecutive_losses >= settings.max_consecutive_losses
            ):
                return RiskGateResult(False, "連続損失上限に到達しています")
            if (
                settings.max_daily_buy_orders > 0
                and snapshot.daily_buy_orders >= settings.max_daily_buy_orders
            ):
                return RiskGateResult(False, "1日のBUY注文上限に到達しています")
            if snapshot.repurchase_cooldown_minutes > 0:
                return RiskGateResult(
                    False,
                    f"再購入クールダウン中です（残り{snapshot.repurchase_cooldown_minutes}分）",
                )
        elif order.side is OrderSide.SELL:
            if (
                settings.max_daily_sell_orders > 0
                and snapshot.daily_sell_orders >= settings.max_daily_sell_orders
            ):
                return RiskGateResult(False, "1日のSELL注文上限に到達しています")
        else:
            return RiskGateResult(False, "未対応の注文サイドです")

        return RiskGateResult(True, "shared risk gate passed")

    return gate
