from unittest.mock import patch

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.execution.legacy_risk_gate import legacy_order_manager_risk_gate


def _buy() -> OrderRequest:
    return OrderRequest(symbol="AAPL", side=OrderSide.BUY, quantity=1)


def _sell() -> OrderRequest:
    return OrderRequest(symbol="AAPL", side=OrderSide.SELL, quantity=1)


@patch("order_manager.calculate_consecutive_losses", return_value=0)
@patch("order_manager.calculate_daily_realized_pnl", return_value=0.0)
@patch("order_manager.calculate_daily_trading_amount", return_value=0.0)
@patch("order_manager.calculate_repurchase_cooldown_remaining_minutes", return_value=0)
@patch("order_manager.calculate_daily_buy_order_count", return_value=0)
def test_allows_safe_buy(*_mocks) -> None:
    assert legacy_order_manager_risk_gate(_buy()).allowed is True


@patch("order_manager.calculate_daily_buy_order_count", return_value=3)
def test_blocks_daily_buy_limit(_mock) -> None:
    result = legacy_order_manager_risk_gate(_buy())
    assert result.allowed is False
    assert result.reason == "daily buy order limit"


@patch("order_manager.calculate_daily_buy_order_count", return_value=0)
@patch("order_manager.calculate_repurchase_cooldown_remaining_minutes", return_value=10)
def test_blocks_repurchase_cooldown(*_mocks) -> None:
    result = legacy_order_manager_risk_gate(_buy())
    assert result.allowed is False
    assert result.reason == "repurchase cooldown"


@patch("order_manager.calculate_daily_sell_order_count", return_value=3)
def test_blocks_daily_sell_limit(_mock) -> None:
    result = legacy_order_manager_risk_gate(_sell())
    assert result.allowed is False
    assert result.reason == "daily sell order limit"


@patch("order_manager.calculate_daily_buy_order_count", return_value=0)
@patch("order_manager.calculate_repurchase_cooldown_remaining_minutes", return_value=0)
@patch("order_manager.calculate_daily_trading_amount", return_value=1_000_000.0)
def test_blocks_daily_trading_amount(*_mocks) -> None:
    result = legacy_order_manager_risk_gate(_buy())
    assert result.allowed is False
    assert result.reason == "daily trading amount limit"


@patch("order_manager.calculate_daily_buy_order_count", return_value=0)
@patch("order_manager.calculate_repurchase_cooldown_remaining_minutes", return_value=0)
@patch("order_manager.calculate_daily_trading_amount", return_value=0.0)
@patch("order_manager.calculate_daily_realized_pnl", return_value=-10_000.0)
def test_blocks_daily_loss_limit(*_mocks) -> None:
    result = legacy_order_manager_risk_gate(_buy())
    assert result.allowed is False
    assert result.reason == "daily loss limit"


@patch("order_manager.calculate_daily_buy_order_count", return_value=0)
@patch("order_manager.calculate_repurchase_cooldown_remaining_minutes", return_value=0)
@patch("order_manager.calculate_daily_trading_amount", return_value=0.0)
@patch("order_manager.calculate_daily_realized_pnl", return_value=0.0)
@patch("order_manager.calculate_consecutive_losses", return_value=3)
def test_blocks_consecutive_losses(*_mocks) -> None:
    result = legacy_order_manager_risk_gate(_buy())
    assert result.allowed is False
    assert result.reason == "consecutive loss limit"
