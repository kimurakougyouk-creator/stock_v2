"""
Paper Trading専用ランナー。

安全方針:
- Paper Tradingが有効な場合だけ実行する
- IBKR Paperが明示的に有効な場合だけIBKRへ送信する
- Live Tradingが有効/解除されている場合は実行しない
- signal_runnerの既存リスク判定を通過した注文だけをIBKR Paperへ渡す
- IBKRでFilled確認できた注文だけを既存取引履歴へ反映する
"""

from pathlib import Path

from config import TRADING_CAPITAL
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.ibkr_signal_runtime import (
    execute_approved_signal_via_ibkr_paper,
)
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
from ai_asset_platform.execution.paper_trading_loop import run_paper_trading_loop
from ai_asset_platform.reports import append_equity_history, legacy_orders_to_equity
from ai_asset_platform.reports.paper_trading_health import evaluate_paper_trading_health
import signal_runner


def _sync_confirmed_fill_to_reporting(order: dict) -> None:
    """Persist one confirmed fill to legacy accounting and total-asset equity.

    This function never sends an order. Duplicate ``order_intent_id`` values are
    idempotent in both the legacy ledger and equity history.
    """
    order_log_path = Path("results") / "paper_orders.jsonl"
    equity_path = Path("results") / "equity_history.csv"
    record_confirmed_fill(
        ticker=str(order["ticker"]),
        side=str(order["side"]),
        filled_quantity=float(order["shares"]),
        avg_fill_price=float(order["reference_price"]),
        order_intent_id=str(order["order_intent_id"]),
        order_log_path=order_log_path,
    )

    orders = signal_runner.load_paper_orders()
    latest_prices = {
        str(item.get("ticker")): float(item.get("reference_price"))
        for item in orders
        if item.get("ticker") and item.get("reference_price") is not None
    }
    points = legacy_orders_to_equity(
        orders,
        initial_cash=float(TRADING_CAPITAL),
        market_prices=latest_prices,
    )
    for point in points:
        append_equity_history(equity_path, point)


def _execute_confirmed_ibkr_paper_order(
    ticker: str,
    signal: str,
    shares: int,
    reference_price: float,
) -> dict:
    """既存signal_runnerの発注点をIBKR Paperの確定約定へ接続する。"""
    normalized_signal = str(signal).upper()
    normalized_shares = int(shares)
    normalized_price = float(reference_price)

    order_intent_id = (
        "signal-runner:"
        f"{ticker}:{normalized_signal}:{normalized_shares}:"
        f"{normalized_price:.8f}"
    )

    execution = execute_approved_signal_via_ibkr_paper(
        ticker=str(ticker),
        signal=normalized_signal,
        shares=normalized_shares,
        order_intent_id=order_intent_id,
    )
    result = execution.broker_result

    filled = (
        execution.attempted
        and result is not None
        and getattr(result, "sent", False)
        and getattr(result, "reached_terminal", False)
        and getattr(result, "last_known_status", None) == "Filled"
        and float(getattr(result, "filled_quantity", 0.0)) > 0
        and getattr(result, "avg_fill_price", None) is not None
        and float(result.avg_fill_price) > 0
    )
    if not filled:
        raise RuntimeError(
            "IBKR PaperでFilledを確認できなかったため、"
            "注文済みとして記録しません。"
        )

    order = {
        "mode": "IBKR_PAPER",
        "ticker": str(ticker),
        "side": normalized_signal,
        "shares": int(float(result.filled_quantity)),
        "reference_price": float(result.avg_fill_price),
        "status": "FILLED",
        "order_intent_id": order_intent_id,
    }
    _sync_confirmed_fill_to_reporting(order)
    return order


def run_paper_trading() -> dict:
    if not SETTINGS.enable_paper_trading:
        raise RuntimeError("Paper Tradingが無効です。実行を中止しました。")
    if not SETTINGS.enable_ibkr_paper:
        raise RuntimeError("IBKR Paperが無効です。実行を中止しました。")
    if SETTINGS.enable_live_trading:
        raise RuntimeError("Live Tradingが有効なため、安全のためPaper試運転を中止しました。")
    if SETTINGS.live_trading_unlocked:
        raise RuntimeError("Live Tradingが解除されているため、安全のためPaper試運転を中止しました。")

    ai_provider = signal_runner._create_configured_ai_provider()
    original_create_paper_order = signal_runner.create_paper_order
    signal_runner.create_paper_order = _execute_confirmed_ibkr_paper_order
    try:
        return signal_runner.run_signal_scan(
            ai_provider=ai_provider,
            allow_orders=True,
            allow_email=False,
        )
    finally:
        signal_runner.create_paper_order = original_create_paper_order


def run_continuous_paper_trading(*, max_runs: int = 3):
    return run_paper_trading_loop(run_once=run_paper_trading, max_runs=max_runs)


def main() -> None:
    print("=" * 50)
    print("AI Asset Platform - IBKR PAPER TRADING")
    print("Live Trading : OFF")
    print("IBKR Paper   : ON")
    print("=" * 50)
    result = run_paper_trading()
    signal_count = len(result["records"])
    error_count = len(result["errors"])
    health = evaluate_paper_trading_health(signal_count=signal_count, error_count=error_count)
    print("=" * 50)
    print("IBKR Paper Trading実行結果")
    print(f"診断結果    : {health.status}")
    print(f"状態        : {health.message}")
    print(f"シグナル件数: {health.signal_count}")
    print(f"エラー件数  : {health.error_count}")
    print("=" * 50)


if __name__ == "__main__":
    main()
