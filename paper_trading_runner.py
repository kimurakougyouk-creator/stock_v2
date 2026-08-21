"""Paper Trading専用ランナー。"""
import json
from config import TRADING_CAPITAL
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.ibkr_signal_runtime import execute_approved_signal_via_ibkr_paper
from ai_asset_platform.execution.paper_trading_loop import run_paper_trading_loop
from ai_asset_platform.reports.equity_history import (
    append_equity_history,
    calculate_equity_curve,
    calculate_maximum_drawdown,
)
from ai_asset_platform.reports.paper_trading_health import evaluate_paper_trading_health
import order_manager
import signal_runner


# IBKR側の初回Paper安全ガードと統合Runnerを一致させる。
# 戦略が100株等を算出しても、実IBKR Paperへ渡すパイロット数量は1株だけ。
PAPER_PILOT_SHARES = 1


def _sync_confirmed_fill_to_reporting() -> None:
    """確定約定から実現損益・総資産履歴・最大DDを冪等に再生成する。注文は送信しない。"""
    order_manager.save_realized_trade_pnls()
    orders = order_manager.load_paper_orders()
    equity_points = calculate_equity_curve(orders, initial_capital=float(TRADING_CAPITAL))
    if not equity_points:
        return
    append_equity_history(equity_points[-1], order_manager.ORDER_LOG_DIR / "equity_history.csv")
    drawdown_path = order_manager.ORDER_LOG_DIR / "paper_drawdown.json"
    payload = {
        "maximum_drawdown": float(calculate_maximum_drawdown(equity_points)),
        "equity_points": len(equity_points),
    }
    drawdown_path.parent.mkdir(parents=True, exist_ok=True)
    drawdown_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _describe_unconfirmed_ibkr_result(execution) -> str:
    """未約定/未送信を推測せず、観測済みBroker情報だけで説明する。"""
    if not execution.attempted:
        return f"IBKR Paper注文は送信前に停止しました: {execution.reason}"

    result = execution.broker_result
    if result is None:
        return "IBKR Paper注文結果を取得できませんでした。注文済みとして記録しません。"

    details = [
        f"status={getattr(result, 'status', None)}",
        f"sent={getattr(result, 'sent', None)}",
        f"order_id={getattr(result, 'order_id', None)}",
        f"terminal={getattr(result, 'reached_terminal', None)}",
        f"timeout={getattr(result, 'timed_out', None)}",
        f"ib_status={getattr(result, 'last_known_status', None)}",
        f"filled={getattr(result, 'filled_quantity', None)}",
        f"avg_price={getattr(result, 'avg_fill_price', None)}",
        f"message={getattr(result, 'message', None)}",
    ]
    errors = getattr(result, "errors", None)
    if errors:
        details.append(f"errors={errors}")
    return (
        "IBKR PaperでFilledを確認できなかったため、注文済みとして記録しません。"
        + " / ".join(details)
    )


def _execute_confirmed_ibkr_paper_order(ticker: str, signal: str, shares: int, reference_price: float) -> dict:
    normalized_signal = str(signal).upper()
    requested_shares = int(shares)
    if requested_shares <= 0:
        raise RuntimeError("IBKR Paperパイロット注文数量は1以上である必要があります。")
    normalized_shares = PAPER_PILOT_SHARES
    normalized_price = float(reference_price)
    order_intent_id = (
        "signal-runner:paper-pilot:"
        f"{ticker}:{normalized_signal}:{normalized_shares}:"
        f"{normalized_price:.8f}"
    )
    execution = execute_approved_signal_via_ibkr_paper(
        ticker=str(ticker),
        signal=normalized_signal,
        shares=normalized_shares,
        order_intent_id=order_intent_id,
        order_log_path=order_manager.ORDER_LOG_PATH,
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
        raise RuntimeError(_describe_unconfirmed_ibkr_result(execution))
    _sync_confirmed_fill_to_reporting()
    return {
        "mode": "IBKR_PAPER",
        "ticker": str(ticker),
        "side": normalized_signal,
        "shares": int(float(result.filled_quantity)),
        "reference_price": float(result.avg_fill_price),
        "status": "FILLED",
        "order_intent_id": order_intent_id,
        "strategy_requested_shares": requested_shares,
        "paper_pilot_shares": normalized_shares,
    }


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
        return signal_runner.run_signal_scan(ai_provider=ai_provider, allow_orders=True, allow_email=False)
    finally:
        signal_runner.create_paper_order = original_create_paper_order


def run_continuous_paper_trading(*, max_runs: int = 3):
    return run_paper_trading_loop(run_once=run_paper_trading, max_runs=max_runs)


def main() -> None:
    print("=" * 50)
    print("AI Asset Platform - IBKR PAPER TRADING")
    print("Live Trading : OFF")
    print("IBKR Paper   : ON")
    print(f"IBKR Pilot Qty: {PAPER_PILOT_SHARES} share")
    print("=" * 50)
    result = run_paper_trading()
    health = evaluate_paper_trading_health(signal_count=len(result["records"]), error_count=len(result["errors"]))
    print("=" * 50)
    print("IBKR Paper Trading実行結果")
    print(f"診断結果    : {health.status}")
    print(f"状態        : {health.message}")
    print(f"シグナル件数: {health.signal_count}")
    print(f"エラー件数  : {health.error_count}")
    print("=" * 50)


if __name__ == "__main__":
    main()
