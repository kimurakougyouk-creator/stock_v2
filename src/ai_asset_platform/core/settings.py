"""
AI資産運用プラットフォーム 共通設定
Version 3.1 development
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlatformSettings:
    system_name: str = "AI Asset Platform"
    system_version: str = "3.1-dev"
    run_mode: str = "DEVELOPMENT"
    enable_ai: bool = True
    emergency_stop: bool = False
    max_order_shares: int = 100
    max_positions: int = 5
    max_position_allocation: float = 0.20
    max_portfolio_allocation: float = 0.80
    max_daily_buy_orders: int = 3
    daily_loss_limit_yen: float = 10_000.0
    max_consecutive_losses: int = 3
    enable_paper_trading: bool = True
    enable_live_trading: bool = False
    supported_markets: tuple[str, ...] = field(
        default_factory=lambda: ("JP_STOCK",)
    )
    supported_brokers: tuple[str, ...] = field(
        default_factory=lambda: ("SBI",)
    )

    @property
    def live_trading_unlocked(self) -> bool:
        """本番取引の二重安全ロックが解除されているかを返す。"""

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
    print("AI      :", SETTINGS.enable_ai)
    print("Stop    :", SETTINGS.emergency_stop)
    print("Max Qty :", SETTINGS.max_order_shares)
    print("Max Pos :", SETTINGS.max_positions)
    print("Max Alloc:", SETTINGS.max_position_allocation)
    print("Portfolio:", SETTINGS.max_portfolio_allocation)
    print("Daily BUY:", SETTINGS.max_daily_buy_orders)
    print("Day Loss:", SETTINGS.daily_loss_limit_yen)
    print("Max Lose:", SETTINGS.max_consecutive_losses)
    print("Paper   :", SETTINGS.enable_paper_trading)
    print("Markets :", ", ".join(SETTINGS.supported_markets))
    print("Brokers :", ", ".join(SETTINGS.supported_brokers))
    print("=" * 40)
