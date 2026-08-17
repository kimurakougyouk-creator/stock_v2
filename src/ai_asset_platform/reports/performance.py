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


@dataclass(frozen=True)
class PerformanceHealth:
    """運用成績の健全度を0～100点で表す。"""

    score: int
    grade: str
    status: str
    sample_score: int
    win_rate_score: int
    profit_factor_score: int
    risk_reward_score: int


def calculate_performance_health(
    performance: PerformanceSummary,
) -> PerformanceHealth:
    """運用成績から健全度スコアを計算する。

    評価項目は次の4項目で、それぞれ最大25点とする。

    - 取引数
    - 勝率
    - プロフィットファクター
    - 純利益と最大ドローダウンのバランス
    """
    if performance.total_trades == 0:
        return PerformanceHealth(
            score=0,
            grade="N/A",
            status="NO_DATA",
            sample_score=0,
            win_rate_score=0,
            profit_factor_score=0,
            risk_reward_score=0,
        )

    if performance.total_trades >= 20:
        sample_score = 25
    elif performance.total_trades >= 10:
        sample_score = 15
    elif performance.total_trades >= 5:
        sample_score = 8
    else:
        sample_score = 3

    if performance.win_rate >= 60:
        win_rate_score = 25
    elif performance.win_rate >= 50:
        win_rate_score = 20
    elif performance.win_rate >= 40:
        win_rate_score = 10
    else:
        win_rate_score = 0

    if performance.profit_factor >= 2.0:
        profit_factor_score = 25
    elif performance.profit_factor >= 1.5:
        profit_factor_score = 20
    elif performance.profit_factor >= 1.0:
        profit_factor_score = 10
    else:
        profit_factor_score = 0

    if performance.net_profit <= 0:
        risk_reward_score = 0
    elif performance.maximum_drawdown == 0:
        risk_reward_score = 25
    else:
        profit_drawdown_ratio = (
            performance.net_profit
            / performance.maximum_drawdown
        )

        if profit_drawdown_ratio >= 2.0:
            risk_reward_score = 25
        elif profit_drawdown_ratio >= 1.0:
            risk_reward_score = 20
        elif profit_drawdown_ratio >= 0.5:
            risk_reward_score = 10
        else:
            risk_reward_score = 0

    score = (
        sample_score
        + win_rate_score
        + profit_factor_score
        + risk_reward_score
    )

    if score >= 80:
        grade = "A"
        status = "EXCELLENT"
    elif score >= 60:
        grade = "B"
        status = "GOOD"
    elif score >= 40:
        grade = "C"
        status = "CAUTION"
    else:
        grade = "D"
        status = "POOR"

    return PerformanceHealth(
        score=score,
        grade=grade,
        status=status,
        sample_score=sample_score,
        win_rate_score=win_rate_score,
        profit_factor_score=profit_factor_score,
        risk_reward_score=risk_reward_score,
    )
