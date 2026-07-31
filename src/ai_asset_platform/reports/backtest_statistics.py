from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestStatistics:
    gross_profit: float
    gross_loss: float
    winning_trades: int
    losing_trades: int

    @property
    def average_profit(self) -> float:
        if self.winning_trades == 0:
            return 0.0
        return self.gross_profit / self.winning_trades

    @property
    def average_loss(self) -> float:
        if self.losing_trades == 0:
            return 0.0
        return self.gross_loss / self.losing_trades

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return 0.0
        return self.gross_profit / self.gross_loss
