from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestSummary:
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_profit: float

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades * 100.0
