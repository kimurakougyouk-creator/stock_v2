from dataclasses import replace
from datetime import datetime, timedelta

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.shared_risk_gate import (
    LegacyRiskSnapshot,
    _today_ibkr_realized_pnl_currency_safe,
    build_shared_risk_gate,
)


def snapshot(**overrides):
    base = LegacyRiskSnapshot(0, 0, 0.0, 0, 0)
    return replace(base, **overrides)


def provider(value):
    return lambda order, settings: value


def _record(*, side, currency, created_at):
    return {
        "mode": "IBKR_PAPER",
        "status": "FILLED",
        "side": side,
        "currency": currency,
        "created_at": created_at,
    }


def test_historical_usd_fill_does_not_poison_todays_jpy_loss_gate():
    yesterday = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    rows = [_record(side="SELL", currency="USD", created_at=yesterday)]
    assert _today_ibkr_realized_pnl_currency_safe(rows) is True


def test_todays_usd_sell_is_currency_unsafe_for_jpy_daily_loss():
    today = datetime.now().isoformat(timespec="seconds")
    rows = [_record(side="SELL", currency="USD", created_at=today)]
    assert _today_ibkr_realized_pnl_currency_safe(rows) is False


def test_todays_usd_buy_alone_does_not_affect_realized_loss_currency():
    today = datetime.now().isoformat(timespec="seconds")
    rows = [_record(side="BUY", currency="USD", created_at=today)]
    assert _today_ibkr_realized_pnl_currency_safe(rows) is True


def test_malformed_ibkr_sell_date_fails_closed():
    rows = [_record(side="SELL", currency="USD", created_at="not-a-date")]
    assert _today_ibkr_realized_pnl_currency_safe(rows) is False


def test_allows_safe_buy():
    gate = build_shared_risk_gate(snapshot_provider=provider(snapshot()))
    assert gate(OrderRequest("SPY", OrderSide.BUY, 1)).allowed is True


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
    assert gate(OrderRequest("SPY", OrderSide.BUY, 1)).allowed is False
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


def test_daily_loss_limit_blocks_buy_but_not_protective_sell():
    state = snapshot(daily_realized_pnl=-10_000.0)
    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, daily_loss_limit_yen=10_000.0),
        snapshot_provider=provider(state),
    )
    assert gate(OrderRequest("SPY", OrderSide.BUY, 1)).allowed is False
    assert gate(OrderRequest("SPY", OrderSide.SELL, 1)).allowed is True


def test_unconverted_ibkr_currency_blocks_new_buy_but_not_sell():
    state = snapshot(daily_realized_pnl_currency_safe=False)
    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, daily_loss_limit_yen=10_000.0),
        snapshot_provider=provider(state),
    )
    buy = gate(OrderRequest("SPY", OrderSide.BUY, 1))
    sell = gate(OrderRequest("SPY", OrderSide.SELL, 1))
    assert buy.allowed is False
    assert "円換算" in buy.reason
    assert sell.allowed is True


def test_consecutive_loss_limit_blocks_buy_but_not_protective_sell():
    state = snapshot(consecutive_losses=3)
    gate = build_shared_risk_gate(
        settings=replace(SETTINGS, max_consecutive_losses=3),
        snapshot_provider=provider(state),
    )
    assert gate(OrderRequest("SPY", OrderSide.BUY, 1)).allowed is False
    assert gate(OrderRequest("SPY", OrderSide.SELL, 1)).allowed is True


def test_disabled_numeric_limits_do_not_block_safe_order():
    gate = build_shared_risk_gate(
        settings=replace(
            SETTINGS,
            daily_loss_limit_yen=0.0,
            max_consecutive_losses=0,
            max_daily_buy_orders=0,
            max_daily_sell_orders=0,
        ),
        snapshot_provider=provider(
            snapshot(
                daily_buy_orders=999,
                daily_sell_orders=999,
                daily_realized_pnl=-999_999.0,
                consecutive_losses=999,
                daily_realized_pnl_currency_safe=False,
            )
        ),
    )
    assert gate(OrderRequest("SPY", OrderSide.BUY, 1)).allowed is True
    assert gate(OrderRequest("SPY", OrderSide.SELL, 1)).allowed is True


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
