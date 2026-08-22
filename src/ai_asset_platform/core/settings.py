"""
AI資産運用プラットフォーム 共通設定
Version 3.1 development
"""

import os
from dataclasses import dataclass, field


def _env_flag(name: str, *, default: bool = False) -> bool:
    """Read an explicit boolean opt-in from the environment.

    Only well-known true/false spellings are accepted. Invalid values fail
    closed instead of accidentally enabling a trading capability.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class PlatformSettings:
    system_name: str = "AI Asset Platform"
    system_version: str = "3.1-dev"
    run_mode: str = "DEVELOPMENT"
    account_currency: str = "JPY"
    enable_ai: bool = True
    minimum_ai_confidence: float = 70.0
    emergency_stop: bool = False
    max_order_shares: int = 100
    max_positions: int = 5
    max_position_allocation: float = 0.20
    max_portfolio_allocation: float = 0.80
    max_portfolio_risk_rate: float = 0.03
    max_daily_buy_orders: int = 3
    max_daily_sell_orders: int = 3
    max_daily_trading_amount_yen: float = 1_000_000.0
    repurchase_cooldown_minutes: int = 60
    daily_loss_limit_yen: float = 10_000.0
    max_consecutive_losses: int = 3
    max_holding_days: int = 30
    trailing_stop_percent = 5.0
    enable_paper_trading: bool = True
    enable_live_trading: bool = False
    enable_ibkr_paper: bool = field(
        default_factory=lambda: _env_flag("AI_ASSET_ENABLE_IBKR_PAPER", default=False)
    )
    supported_markets: tuple[str, ...] = field(
        default_factory=lambda: ("JP_STOCK", "US_STOCK", "US_ETF")
    )
    supported_brokers: tuple[str, ...] = field(
        default_factory=lambda: ("SBI", "IBKR")
    )

    @property
    def live_trading_unlocked(self) -> bool:
        return (
            self.run_mode == "LIVE"
            and self.enable_live_trading is True
            and self.emergency_stop is False
        )


SETTINGS = PlatformSettings()


if __name__ == "__main__":
    print("=" * 40)
    print(SETTINGS.system_name)
    print("Version :", SETTINGS.system_version)
    print("Mode    :", SETTINGS.run_mode)
    print("Account :", SETTINGS.account_currency)
    print("AI      :", SETTINGS.enable_ai)
    print("AI Conf :", SETTINGS.minimum_ai_confidence)
    print("Stop    :", SETTINGS.emergency_stop)
    print("Max Qty :", SETTINGS.max_order_shares)
    print("Max Pos :", SETTINGS.max_positions)
    print("Max Alloc:", SETTINGS.max_position_allocation)
    print("Portfolio:", SETTINGS.max_portfolio_allocation)
    print("Risk Rate:", SETTINGS.max_portfolio_risk_rate)
    print("Daily BUY:", SETTINGS.max_daily_buy_orders)
    print("Daily SELL:", SETTINGS.max_daily_sell_orders)
    print("Day Amount:", SETTINGS.max_daily_trading_amount_yen)
    print("Cooldown :", SETTINGS.repurchase_cooldown_minutes)
    print("Day Loss:", SETTINGS.daily_loss_limit_yen)
    print("Max Lose:", SETTINGS.max_consecutive_losses)
    print("Hold Days:", SETTINGS.max_holding_days)
    print("Paper   :", SETTINGS.enable_paper_trading)
    print("IBKR Paper:", SETTINGS.enable_ibkr_paper)
    print("Markets :", ", ".join(SETTINGS.supported_markets))
    print("Brokers :", ", ".join(SETTINGS.supported_brokers))
    print("=" * 40)
