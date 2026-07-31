from ai_asset_platform.reports.backtest_evaluator import evaluate_best_report
from ai_asset_platform.reports.backtest_report import BacktestReport
from ai_asset_platform.reports.backtest_statistics import BacktestStatistics
from ai_asset_platform.reports.backtest_summary import BacktestSummary


def create_report(total_profit: float, wins: int) -> BacktestReport:
    summary = BacktestSummary(
        total_trades=10,
        winning_trades=wins,
        losing_trades=10 - wins,
        total_profit=total_profit,
    )

    statistics = BacktestStatistics(
        gross_profit=max(total_profit, 0.0),
        gross_loss=50000.0,
        winning_trades=wins,
        losing_trades=10 - wins,
    )

    return BacktestReport(summary, statistics)


def test_evaluate_best_report():
    reports = [
        create_report(200000.0, 6),
        create_report(200000.0, 8),
        create_report(150000.0, 9),
    ]

    best = evaluate_best_report(reports)

    assert best is not None
    assert best.summary.total_profit == 200000.0
    assert best.summary.winning_trades == 8


def test_evaluate_best_report_empty():
    assert evaluate_best_report([]) is None
