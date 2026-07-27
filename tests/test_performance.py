from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.portfolio.portfolio import Portfolio
from ai_asset_platform.reports import calculate_performance


def test_portfolio_records_each_realized_trade_pnl() -> None:
    portfolio = Portfolio()

    portfolio.apply_fill(
        FillResult(
            order_id="1",
            symbol="7203.T",
            side=OrderSide.BUY,
            quantity=100,
            fill_price=3000.0,
        )
    )
    portfolio.apply_fill(
        FillResult(
            order_id="2",
            symbol="7203.T",
            side=OrderSide.SELL,
            quantity=40,
            fill_price=3200.0,
        )
    )
    portfolio.apply_fill(
        FillResult(
            order_id="3",
            symbol="7203.T",
            side=OrderSide.SELL,
            quantity=60,
            fill_price=2900.0,
        )
    )

    assert portfolio.realized_trade_pnls == [8000.0, -6000.0]
    assert portfolio.realized_pnl == 2000.0

    copied_history = portfolio.realized_trade_pnls
    copied_history.clear()

    assert portfolio.realized_trade_pnls == [8000.0, -6000.0]


def test_calculate_performance_summary() -> None:
    summary = calculate_performance(
        [10_000.0, -4_000.0, 6_000.0, -2_000.0, 0.0]
    )

    assert summary.total_trades == 5
    assert summary.winning_trades == 2
    assert summary.losing_trades == 2
    assert summary.break_even_trades == 1
    assert summary.win_rate == 40.0
    assert summary.gross_profit == 16_000.0
    assert summary.gross_loss == -6_000.0
    assert summary.net_profit == 10_000.0
    assert summary.average_profit == 8_000.0
    assert summary.average_loss == -3_000.0
    assert summary.largest_profit == 10_000.0
    assert summary.largest_loss == -4_000.0


def test_empty_performance_summary_returns_zero() -> None:
    summary = calculate_performance([])

    assert summary.total_trades == 0
    assert summary.win_rate == 0.0
    assert summary.net_profit == 0.0
    assert summary.average_profit == 0.0
    assert summary.average_loss == 0.0
    assert summary.largest_profit == 0.0
    assert summary.largest_loss == 0.0
