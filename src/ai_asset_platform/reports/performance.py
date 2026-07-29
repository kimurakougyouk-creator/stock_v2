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
    profit_factor: float
    maximum_winning_streak: int
    maximum_losing_streak: int
    maximum_drawdown: float


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

    if gross_loss < 0:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    maximum_winning_streak = 0
    maximum_losing_streak = 0
    current_winning_streak = 0
    current_losing_streak = 0

    cumulative_profit = 0.0
    peak_profit = 0.0
    maximum_drawdown = 0.0

    for pnl in pnls:
        cumulative_profit += pnl
        peak_profit = max(peak_profit, cumulative_profit)
        maximum_drawdown = max(
            maximum_drawdown,
            peak_profit - cumulative_profit,
        )

        if pnl > 0:
            current_winning_streak += 1
            current_losing_streak = 0
            maximum_winning_streak = max(
                maximum_winning_streak,
                current_winning_streak,
            )
        elif pnl < 0:
            current_losing_streak += 1
            current_winning_streak = 0
            maximum_losing_streak = max(
                maximum_losing_streak,
                current_losing_streak,
            )
        else:
            current_winning_streak = 0
            current_losing_streak = 0

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
        profit_factor=profit_factor,
        maximum_winning_streak=maximum_winning_streak,
        maximum_losing_streak=maximum_losing_streak,
        maximum_drawdown=maximum_drawdown,
    )
