from ai_asset_platform.reports.backtest_report import BacktestReport
from ai_asset_platform.reports.backtest_selector import select_best_report
from ai_asset_platform.reports.backtest_statistics import BacktestStatistics
from ai_asset_platform.reports.backtest_summary import BacktestSummary


def create_report(total_profit: float) -> BacktestReport:
    summary = BacktestSummary(
        total_trades=10,
        winning_trades=7,
        losing_trades=3,
        total_profit=total_profit,
    )

    statistics = BacktestStatistics(
        gross_profit=max(total_profit, 0.0),
        gross_loss=50000.0,
        winning_trades=7,
        losing_trades=3,
    )

    return BacktestReport(summary, statistics)


def test_select_best_report():
    reports = [
        create_report(100000.0),
        create_report(250000.0),
        create_report(180000.0),
    ]

    best = select_best_report(reports)

    assert best is not None
    assert best.summary.total_profit == 250000.0


def test_select_best_report_empty():
    assert select_best_report([]) is None
