"""Paper Tradingの運用成績を集計する。"""

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PerformanceSummary:
    total_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_profit: float
    average_profit: float
    average_loss: float
    largest_profit: float
    largest_loss: float


def calculate_performance(
    realized_trade_pnls: Iterable[float],
) -> PerformanceSummary:
    """売却約定ごとの実現損益から運用成績を計算する。"""
    pnls = [float(pnl) for pnl in realized_trade_pnls]

    profits = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    break_even_count = sum(1 for pnl in pnls if pnl == 0)

    total_trades = len(pnls)
    win_rate = (
        len(profits) / total_trades * 100
        if total_trades
        else 0.0
    )

    gross_profit = sum(profits)
    gross_loss = sum(losses)

    return PerformanceSummary(
        total_trades=total_trades,
        winning_trades=len(profits),
        losing_trades=len(losses),
        break_even_trades=break_even_count,
        win_rate=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=sum(pnls),
        average_profit=(
            gross_profit / len(profits)
            if profits
            else 0.0
        ),
        average_loss=(
            gross_loss / len(losses)
            if losses
            else 0.0
        ),
        largest_profit=max(profits, default=0.0),
        largest_loss=min(losses, default=0.0),
    )
