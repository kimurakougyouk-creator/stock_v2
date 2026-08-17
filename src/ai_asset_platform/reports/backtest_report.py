from dataclasses import dataclass

from ai_asset_platform.reports.backtest_statistics import BacktestStatistics
from ai_asset_platform.reports.backtest_summary import BacktestSummary


@dataclass(frozen=True)
class BacktestReport:
    summary: BacktestSummary
    statistics: BacktestStatistics

    def as_dict(self) -> dict:
        return {
            "total_trades": self.summary.total_trades,
            "winning_trades": self.summary.winning_trades,
            "losing_trades": self.summary.losing_trades,
            "total_profit": self.summary.total_profit,
            "win_rate": self.summary.win_rate,
            "average_profit": self.statistics.average_profit,
            "average_loss": self.statistics.average_loss,
            "profit_factor": self.statistics.profit_factor,
        }
