from ai_asset_platform.reports.backtest_report import BacktestReport
from ai_asset_platform.reports.backtest_report_export import export_backtest_report_csv
from ai_asset_platform.reports.backtest_statistics import BacktestStatistics
from ai_asset_platform.reports.backtest_summary import BacktestSummary


def test_export_backtest_report_csv():
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

    csv_text = export_backtest_report_csv(report)

    assert "total_trades" in csv_text
    assert "profit_factor" in csv_text
    assert "150000.0" in csv_text
    assert "3.5" in csv_text
