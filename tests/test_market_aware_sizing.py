import pytest

from ai_asset_platform.risk.market_sizing import (
    MarketSizingError,
    MarketSizingSpec,
    calculate_market_position_size,
)


def test_jpy_stock_uses_explicit_100_share_increment():
    result = calculate_market_position_size(
        MarketSizingSpec(
            account_equity=1_000_000,
            account_currency="JPY",
            instrument_currency="JPY",
            entry_price=1_000,
            risk_per_trade_rate=0.01,
            stop_loss_rate=0.03,
            quantity_increment=100,
            minimum_quantity=100,
            max_position_allocation=1.0,
        )
    )
    # 10,000 JPY risk budget / 30 JPY loss per share = 333..., floor to 300.
    assert result.quantity == 300
    assert result.fx_to_account_rate == 1
    assert result.loss_per_quantity_account == 30
    assert result.notional_account == 300_000


def test_us_stock_in_jpy_account_requires_explicit_fx_rate():
    spec = MarketSizingSpec(
        account_equity=1_000_000,
        account_currency="JPY",
        instrument_currency="USD",
        entry_price=100,
        risk_per_trade_rate=0.01,
        stop_loss_rate=0.03,
        quantity_increment=1,
        minimum_quantity=1,
    )
    with pytest.raises(MarketSizingError, match="explicit fx_to_account_rate"):
        calculate_market_position_size(spec)


def test_us_stock_converts_loss_and_notional_to_jpy_before_sizing():
    result = calculate_market_position_size(
        MarketSizingSpec(
            account_equity=1_000_000,
            account_currency="JPY",
            instrument_currency="USD",
            entry_price=100,
            risk_per_trade_rate=0.01,
            stop_loss_rate=0.03,
            quantity_increment=1,
            minimum_quantity=1,
            fx_to_account_rate=150,
            max_position_allocation=0.20,
        )
    )
    # Risk: 10,000 / (100 * 150 * 3%) = 22.22 -> 22.
    # Allocation: 200,000 / 15,000 = 13.33 -> allocation is tighter -> 13.
    assert result.quantity == 13
    assert result.loss_per_quantity_account == 450
    assert result.notional_account == 195_000


def test_derivative_multiplier_changes_risk_in_account_currency():
    result = calculate_market_position_size(
        MarketSizingSpec(
            account_equity=10_000_000,
            account_currency="USD",
            instrument_currency="USD",
            entry_price=5_000,
            risk_per_trade_rate=0.01,
            stop_loss_rate=0.01,
            quantity_increment=1,
            minimum_quantity=1,
            contract_multiplier=50,
            max_position_allocation=1.0,
        )
    )
    # Per-contract loss = 5,000 * 50 * 1% = 2,500 USD; budget=100,000 => 40.
    assert result.quantity == 40
    assert result.loss_per_quantity_account == 2_500


def test_quantity_step_is_not_assumed_to_be_integer():
    result = calculate_market_position_size(
        MarketSizingSpec(
            account_equity=10_000,
            account_currency="USD",
            instrument_currency="USD",
            entry_price=20,
            risk_per_trade_rate=0.01,
            stop_loss_rate=0.10,
            quantity_increment=0.25,
            minimum_quantity=0.25,
        )
    )
    # Risk budget 100 / loss 2 = 50 units; exact 0.25 step.
    assert result.quantity == 50.0


def test_below_broker_minimum_quantity_returns_zero_not_unsafe_round_up():
    result = calculate_market_position_size(
        MarketSizingSpec(
            account_equity=1_000,
            account_currency="USD",
            instrument_currency="USD",
            entry_price=500,
            risk_per_trade_rate=0.01,
            stop_loss_rate=0.10,
            quantity_increment=1,
            minimum_quantity=1,
        )
    )
    assert result.quantity == 0
    assert result.notional_account == 0


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"quantity_increment": 0}, "quantity_increment"),
        ({"minimum_quantity": 0}, "minimum_quantity"),
        ({"contract_multiplier": 0}, "contract_multiplier"),
        ({"risk_per_trade_rate": 1.1}, "risk_per_trade_rate"),
        ({"stop_loss_rate": 0}, "stop_loss_rate"),
        ({"max_position_allocation": 0}, "max_position_allocation"),
    ],
)
def test_invalid_sizing_inputs_fail_closed(overrides, match):
    values = dict(
        account_equity=1_000_000,
        account_currency="JPY",
        instrument_currency="JPY",
        entry_price=1_000,
        risk_per_trade_rate=0.01,
        stop_loss_rate=0.03,
        quantity_increment=100,
        minimum_quantity=100,
        contract_multiplier=1,
        max_position_allocation=1,
    )
    values.update(overrides)
    with pytest.raises(MarketSizingError, match=match):
        calculate_market_position_size(MarketSizingSpec(**values))


def test_same_currency_rejects_non_one_fx_rate():
    with pytest.raises(MarketSizingError, match="same-currency"):
        calculate_market_position_size(
            MarketSizingSpec(
                account_equity=1_000_000,
                account_currency="JPY",
                instrument_currency="JPY",
                entry_price=1_000,
                risk_per_trade_rate=0.01,
                stop_loss_rate=0.03,
                quantity_increment=100,
                minimum_quantity=100,
                fx_to_account_rate=150,
            )
        )
