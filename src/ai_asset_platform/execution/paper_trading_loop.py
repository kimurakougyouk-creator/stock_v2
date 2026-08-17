from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ai_asset_platform.reports.paper_trading_health import (
    PaperTradingHealth,
    evaluate_paper_trading_health,
)


@dataclass(frozen=True)
class PaperTradingLoopResult:
    completed_runs: int
    stopped_early: bool
    last_health: PaperTradingHealth


def run_paper_trading_loop(
    *,
    run_once: Callable[[], dict],
    max_runs: int = 3,
) -> PaperTradingLoopResult:
    """
    Paper Tradingを指定回数まで連続実行する。

    ERRORを検出した場合は、その時点で自動停止する。
    """

    max_runs = int(max_runs)

    if max_runs <= 0:
        raise ValueError("max_runsは1以上にしてください。")

    last_health: PaperTradingHealth | None = None

    for run_number in range(1, max_runs + 1):
        result = run_once()

        health = evaluate_paper_trading_health(
            signal_count=len(result["records"]),
            error_count=len(result["errors"]),
        )
        last_health = health

        if health.status == "ERROR":
            return PaperTradingLoopResult(
                completed_runs=run_number,
                stopped_early=True,
                last_health=health,
            )

    assert last_health is not None

    return PaperTradingLoopResult(
        completed_runs=max_runs,
        stopped_early=False,
        last_health=last_health,
    )
