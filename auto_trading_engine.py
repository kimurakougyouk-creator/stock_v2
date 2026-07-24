from pathlib import Path
from typing import Any

from execution import BrokerFactory, Order, record_dry_run_orders
from stability import FatalOperationalError, create_daily_logger, safe_execute

DRY_RUN_MODES = {"dry_run", "dry-run", "paper"}


def run_dry_run_trading_cycle(
    ticker: str,
    backtest_result: dict[str, Any],
    *,
    broker_mode: str = "dry_run",
    order_file: str | Path = "results/dry_run_orders.json",
    available_cash: float,
    dry_run: bool = True,
) -> list[Order]:
    """売買シグナル由来のバックテスト結果からdry-run注文を生成・記録する。"""

    logger = create_daily_logger("auto_trading_engine", log_dir="results")

    def operation() -> list[Order]:
        _ensure_dry_run_only(broker_mode, dry_run)
        broker = BrokerFactory.create(broker_mode, order_file=order_file)
        return record_dry_run_orders(
            ticker,
            backtest_result,
            broker,
            available_cash=available_cash,
            dry_run=dry_run,
        )

    return safe_execute(operation, logger, default=[])


def _ensure_dry_run_only(broker_mode: str, dry_run: bool) -> None:
    normalized_mode = (broker_mode or "dry_run").lower()
    if not dry_run or normalized_mode not in DRY_RUN_MODES:
        raise FatalOperationalError("実注文は未実装です。DryRunのみ実行できます。")
