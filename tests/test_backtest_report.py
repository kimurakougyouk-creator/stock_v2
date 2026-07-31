from ai_asset_platform.reports.backtest_report import BacktestReport
from ai_asset_platform.reports.backtest_statistics import BacktestStatistics
from ai_asset_platform.reports.backtest_summary import BacktestSummary


def test_backtest_report_as_dict():
    summary = BacktestSummary(
        total_trades=10,
        winning_trades=7,
        losing_trades=3,
        total_profit=150000.0,
    )

    statistics = BacktestStatistics(
        gross_profit=210000.0,
        gross_loss=60000.0,
        winning_trades=7,
        losing_trades=3,
    )

    report = BacktestReport(summary, statistics)

    data = report.as_dict()

    assert data["total_trades"] == 10
    assert data["winning_trades"] == 7
    assert data["losing_trades"] == 3
    assert data["total_profit"] == 150000.0
    assert data["win_rate"] == 70.0
    assert data["average_profit"] == 30000.0
    assert data["average_loss"] == 20000.0
    assert data["profit_factor"] == 3.5
