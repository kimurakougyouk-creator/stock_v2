"""Regression tests for Japanese 100-share lot risk boundaries.

These tests document the safe boundary implied by the current production
settings. They intentionally do not loosen any trading limit.
"""

from config import LOT_SIZE, RISK_PER_TRADE_RATE, STOP_LOSS_RATE, TRADING_CAPITAL
from ai_asset_platform.core.settings import PlatformSettings
from risk_manager import calculate_position_size


def test_current_jp_lot_is_100_shares():
    assert LOT_SIZE == 100


def test_fixed_stop_risk_allows_one_lot_at_3333_yen():
    shares = calculate_position_size(
        trading_capital=TRADING_CAPITAL,
        risk_per_trade_rate=RISK_PER_TRADE_RATE,
        entry_price=3333.0,
        stop_loss_rate=STOP_LOSS_RATE,
        lot_size=LOT_SIZE,
    )
    assert shares == 100


def test_fixed_stop_risk_rejects_one_lot_above_boundary():
    shares = calculate_position_size(
        trading_capital=TRADING_CAPITAL,
        risk_per_trade_rate=RISK_PER_TRADE_RATE,
        entry_price=3334.0,
        stop_loss_rate=STOP_LOSS_RATE,
        lot_size=LOT_SIZE,
    )
    assert shares == 0


def test_position_allocation_is_tighter_than_fixed_stop_risk_for_one_lot():
    settings = PlatformSettings()
    allocation_yen = TRADING_CAPITAL * settings.max_position_allocation
    max_price_for_one_lot = allocation_yen / LOT_SIZE

    # 1,000,000 yen * 20% / 100 shares = 2,000 yen/share.
    assert max_price_for_one_lot == 2000.0


def test_one_lot_at_2000_yen_respects_position_allocation():
    settings = PlatformSettings()
    order_value = 2000.0 * LOT_SIZE
    allocation_limit = TRADING_CAPITAL * settings.max_position_allocation
    assert order_value <= allocation_limit


def test_one_lot_above_2000_yen_exceeds_position_allocation():
    settings = PlatformSettings()
    order_value = 2000.01 * LOT_SIZE
    allocation_limit = TRADING_CAPITAL * settings.max_position_allocation
    assert order_value > allocation_limit


def test_live_trading_remains_disabled_in_default_settings():
    settings = PlatformSettings()
    assert settings.enable_live_trading is False
    assert settings.live_trading_unlocked is False
