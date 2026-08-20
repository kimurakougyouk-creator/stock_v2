from __future__ import annotations

from dataclasses import dataclass
from time import sleep
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
    interval_seconds: float = 0.0,
    sleep_fn: Callable[[float], None] = sleep,
) -> PaperTradingLoopResult:
    """Paper Tradingを安全に指定回数まで連続実行する。

    ERRORを検出した場合は即時停止する。各正常実行の間には任意の待機時間を
    入れられる。最後の実行後やERROR後には待機しない。
    """

    max_runs = int(max_runs)
    interval_seconds = float(interval_seconds)

    if max_runs <= 0:
        raise ValueError("max_runsは1以上にしてください。")
    if interval_seconds < 0:
        raise ValueError("interval_secondsは0以上にしてください。")

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

        if run_number < max_runs and interval_seconds > 0:
            sleep_fn(interval_seconds)

    assert last_health is not None

    return PaperTradingLoopResult(
        completed_runs=max_runs,
        stopped_early=False,
        last_health=last_health,
    )
