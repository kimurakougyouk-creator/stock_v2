from ai_asset_platform.reports.backtest_statistics import BacktestStatistics


def test_backtest_statistics():
    stats = BacktestStatistics(
        gross_profit=200000.0,
        gross_loss=100000.0,
        winning_trades=8,
        losing_trades=4,
    )

    assert stats.average_profit == 25000.0
    assert stats.average_loss == 25000.0
    assert stats.profit_factor == 2.0


def test_backtest_statistics_zero_values():
    stats = BacktestStatistics(
        gross_profit=0.0,
        gross_loss=0.0,
        winning_trades=0,
        losing_trades=0,
    )

    assert stats.average_profit == 0.0
    assert stats.average_loss == 0.0
    assert stats.profit_factor == 0.0
