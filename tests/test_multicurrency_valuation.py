import pytest

from ai_asset_platform.reports.multicurrency_valuation import (
    MulticurrencyValuationError,
    PositionValuationInput,
    value_portfolio,
    value_position,
)


def test_same_currency_stock_needs_no_fx_rate():
    result = value_position(
        PositionValuationInput(
            symbol="9432",
            quantity=100,
            average_cost=150,
            market_price=160,
            instrument_currency="JPY",
            account_currency="JPY",
        )
    )
    assert result.cost_basis_account == 15_000
    assert result.market_value_account == 16_000
    assert result.unrealized_pnl_account == 1_000
    assert result.fx_to_account_rate == 1


def test_us_stock_in_jpy_account_requires_explicit_conversion():
    with pytest.raises(MulticurrencyValuationError, match="explicit fx_to_account_rate"):
        value_position(
            PositionValuationInput(
                symbol="SPY",
                quantity=1,
                average_cost=700,
                market_price=710,
                instrument_currency="USD",
                account_currency="JPY",
            )
        )


def test_us_stock_is_valued_in_jpy_with_explicit_conversion():
    result = value_position(
        PositionValuationInput(
            symbol="SPY",
            quantity=2,
            average_cost=700,
            market_price=710,
            instrument_currency="USD",
            account_currency="JPY",
            fx_to_account_rate=150,
        )
    )
    assert result.cost_basis_account == 210_000
    assert result.market_value_account == 213_000
    assert result.unrealized_pnl_account == 3_000


def test_derivative_multiplier_is_applied_explicitly():
    result = value_position(
        PositionValuationInput(
            symbol="ES",
            quantity=1,
            average_cost=5_000,
            market_price=5_010,
            instrument_currency="USD",
            account_currency="USD",
            contract_multiplier=50,
        )
    )
    assert result.cost_basis_account == 250_000
    assert result.market_value_account == 250_500
    assert result.unrealized_pnl_account == 500


def test_portfolio_sums_only_positions_using_same_account_currency():
    result = value_portfolio(
        [
            PositionValuationInput(
                symbol="9432", quantity=100, average_cost=150, market_price=160,
                instrument_currency="JPY", account_currency="JPY"
            ),
            PositionValuationInput(
                symbol="SPY", quantity=1, average_cost=700, market_price=710,
                instrument_currency="USD", account_currency="JPY",
                fx_to_account_rate=150,
            ),
        ],
        account_currency="JPY",
        cash_account=1_000_000,
    )
    assert result.positions_market_value_account == 122_500
    assert result.unrealized_pnl_account == 2_500
    assert result.total_equity_account == 1_122_500
    assert len(result.positions) == 2


def test_same_currency_rejects_non_one_fx_rate():
    with pytest.raises(MulticurrencyValuationError, match="same-currency"):
        value_position(
            PositionValuationInput(
                symbol="9432", quantity=100, average_cost=150, market_price=160,
                instrument_currency="JPY", account_currency="JPY",
                fx_to_account_rate=150,
            )
        )


def test_portfolio_rejects_mixed_account_currency_rows():
    with pytest.raises(MulticurrencyValuationError, match="portfolio account currency"):
        value_portfolio(
            [
                PositionValuationInput(
                    symbol="SPY", quantity=1, average_cost=700, market_price=710,
                    instrument_currency="USD", account_currency="USD"
                )
            ],
            account_currency="JPY",
            cash_account=1_000_000,
        )
