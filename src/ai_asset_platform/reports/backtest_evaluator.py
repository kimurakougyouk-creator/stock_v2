from ai_asset_platform.reports.backtest_report import BacktestReport


def evaluate_best_report(reports: list[BacktestReport]) -> BacktestReport | None:
    if not reports:
        return None

    return max(
        reports,
        key=lambda report: (
            report.summary.total_profit,
            report.summary.win_rate,
        ),
    )
