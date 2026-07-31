from ai_asset_platform.reports.backtest_summary import BacktestSummary


def test_backtest_summary():
    summary = BacktestSummary(
        total_trades=10,
        winning_trades=7,
        losing_trades=3,
        total_profit=125000.0,
    )

    assert summary.total_trades == 10
    assert summary.winning_trades == 7
    assert summary.losing_trades == 3
    assert summary.total_profit == 125000.0
    assert summary.win_rate == 70.0


def test_backtest_summary_empty():
    summary = BacktestSummary(
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        total_profit=0.0,
    )

    assert summary.win_rate == 0.0
