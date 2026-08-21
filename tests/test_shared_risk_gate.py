from dataclasses import replace

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.shared_risk_gate import (
    LegacyRiskSnapshot,
    build_shared_risk_gate,
)


def snapshot(**overrides):
    base = LegacyRiskSnapshot(0, 0, 0.0, 0, 0)
    return replace(base, **overrides)


def provider(value):
    return lambda order, settings: value


def test_allows_safe_buy():
    gate = build_shared_risk_gate(snapshot_provider=provider(snapshot()))
    result = gate(OrderRequest("SPY", OrderSide.BUY, 1))
    assert result.allowed is True


def test_emergency_stop_blocks_before_state_read():
    called = False

    def should_not_run(order, settings):
        nonlocal called
        called = True
        return snapshot()

    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, emergency_stop=True),
        snapshot_provider=should_not_run,
    )
    result = gate(OrderRequest("SPY", OrderSide.BUY, 1))
    assert result.allowed is False
    assert called is False


def test_paper_disabled_blocks():
    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, enable_paper_trading=False),
        snapshot_provider=provider(snapshot()),
    )
    assert gate(OrderRequest("SPY", OrderSide.BUY, 1)).allowed is False


def test_max_order_shares_blocks():
    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, max_order_shares=1),
        snapshot_provider=provider(snapshot()),
    )
    assert gate(OrderRequest("SPY", OrderSide.BUY, 2)).allowed is False


def test_daily_buy_limit_blocks():
    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, max_daily_buy_orders=3),
        snapshot_provider=provider(snapshot(daily_buy_orders=3)),
    )
    assert gate(OrderRequest("SPY", OrderSide.BUY, 1)).allowed is False


def test_daily_sell_limit_blocks():
    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, max_daily_sell_orders=3),
        snapshot_provider=provider(snapshot(daily_sell_orders=3)),
    )
    assert gate(OrderRequest("SPY", OrderSide.SELL, 1)).allowed is False


def test_daily_loss_limit_blocks():
    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, daily_loss_limit_yen=10_000.0),
        snapshot_provider=provider(snapshot(daily_realized_pnl=-10_000.0)),
    )
    assert gate(OrderRequest("SPY", OrderSide.BUY, 1)).allowed is False


def test_consecutive_loss_limit_blocks():
    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, max_consecutive_losses=3),
        snapshot_provider=provider(snapshot(consecutive_losses=3)),
    )
    assert gate(OrderRequest("SPY", OrderSide.BUY, 1)).allowed is False


def test_repurchase_cooldown_blocks_buy():
    gate = build_shared_risk_gate(
        snapshot_provider=provider(snapshot(repurchase_cooldown_minutes=12)),
    )
    result = gate(OrderRequest("SPY", OrderSide.BUY, 1))
    assert result.allowed is False
    assert "12" in result.reason


def test_snapshot_failure_fails_closed():
    def broken(order, settings):
        raise OSError("ledger unavailable")

    gate = build_shared_risk_gate(snapshot_provider=broken)
    result = gate(OrderRequest("SPY", OrderSide.BUY, 1))
    assert result.allowed is False
    assert "Risk状態" in result.reason
