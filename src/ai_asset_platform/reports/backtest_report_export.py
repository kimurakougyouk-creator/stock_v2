from ai_asset_platform.reports.backtest_report import BacktestReport


def export_backtest_report_csv(report: BacktestReport) -> str:
    data = report.as_dict()

    header = ",".join(data.keys())
    values = ",".join(str(v) for v in data.values())

    return f"{header}\n{values}\n"
