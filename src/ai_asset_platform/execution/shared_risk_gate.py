"""Shared fail-closed pre-send risk gate for migrated execution paths.

The gate reads the durable Paper ledger but evaluates realized PnL and loss
streaks in the configured account currency. Cross-currency IBKR fills therefore
require the explicit per-fill FX evidence captured with the confirmed fill. No
FX rate is guessed, no broker order is created here, and Live is never enabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.core.settings import PlatformSettings, SETTINGS
from ai_asset_platform.execution.service import RiskGateResult
from ai_asset_platform.reports.multicurrency_trade_history import (
    MulticurrencyTradeHistoryError,
    consecutive_losses_account_currency,
    realized_pnl_for_date,
)


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
    """Compatibility helper: reject today's unconverted non-JPY IBKR SELL rows.

    The authoritative risk snapshot now reconstructs realized PnL using the
    explicit-FX trade-history engine. This helper remains for regression tests
    and diagnostics only.
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
            return False
        if created.date() != today:
            continue
        currency = str(record.get("currency", "")).strip().upper()
        if currency == "JPY":
            continue
        try:
            rate = float(record.get("fx_to_account_rate"))
        except (TypeError, ValueError):
            return False
        if rate <= 0:
            return False
    return True


def load_legacy_risk_snapshot(
    order: OrderRequest,
    settings: PlatformSettings = SETTINGS,
) -> LegacyRiskSnapshot:
    """Read safety state from the durable Paper ledger in account currency.

    If explicit-FX accounting cannot prove the realized PnL/loss streak, the
    snapshot marks currency safety false. The BUY gate then fails closed while
    protective SELLs remain available.
    """
    from order_manager import (
        calculate_daily_buy_order_count,
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
    currency_safe = True
    daily_realized = 0.0
    consecutive_losses = 0
    try:
        daily_realized = realized_pnl_for_date(
            accounting_orders,
            target_date=date.today(),
            account_currency=settings.account_currency,
        )
        consecutive_losses = consecutive_losses_account_currency(
            accounting_orders,
            account_currency=settings.account_currency,
        )
    except MulticurrencyTradeHistoryError:
        currency_safe = False

    return LegacyRiskSnapshot(
        daily_buy_orders=calculate_daily_buy_order_count(),
        daily_sell_orders=calculate_daily_sell_order_count(),
        daily_realized_pnl=daily_realized,
        consecutive_losses=consecutive_losses,
        repurchase_cooldown_minutes=cooldown,
        daily_realized_pnl_currency_safe=currency_safe,
    )


def build_shared_risk_gate(
    *,
    settings: PlatformSettings = SETTINGS,
    snapshot_provider: SnapshotProvider = load_legacy_risk_snapshot,
):
    """Return a fail-closed RiskGate compatible with ExecutionService.

    Loss streak/daily-loss controls intentionally block new BUY exposure only,
    so a protective SELL remains possible. Disabled numeric limits (<= 0) are
    not treated as already exhausted.
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
                    "IBKR損益を口座通貨へ安全に換算（円換算を含む）できないため新規BUYを拒否しました",
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
