"""Paper Trading専用ランナー。"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from config import TRADING_CAPITAL
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.confirmed_fill_evidence import (
    confirmed_fill_from_broker_result,
)
from ai_asset_platform.execution.ibkr_signal_runtime import execute_approved_signal_via_ibkr_paper
from ai_asset_platform.execution.paper_trading_loop import run_paper_trading_loop
from ai_asset_platform.execution.signal_order_bridge import (
    _instrument_for_ticker,
    verified_paper_test_quantity_for_ticker,
)
from ai_asset_platform.reports.confirmed_accounting import (
    ConfirmedAccountingCurrencyError,
    audit_confirmed_accounting_file,
)
from ai_asset_platform.reports.equity_history import (
    append_equity_history,
    calculate_equity_curve,
    calculate_maximum_drawdown,
)
from ai_asset_platform.reports.paper_trading_health import evaluate_paper_trading_health
import order_manager
import signal_runner


_US_ET = ZoneInfo("America/New_York")
_JST = ZoneInfo("Asia/Tokyo")


def _paper_signal_session_key(ticker: str, now: datetime | None = None) -> str:
    """Return a price-independent trading-date key for the verified pilot.

    Tokyo symbols use the Tokyo calendar date; current US pilot symbols use the
    New York calendar date. The key deliberately excludes reference price so an
    uncertain order cannot be retried merely because the quote changed.
    """
    zone = _JST if str(ticker).strip().upper().endswith(".T") else _US_ET
    current = now.astimezone(zone) if now is not None else datetime.now(zone)
    return current.date().isoformat()


def _write_accounting_status(*, safe: bool, reason: str | None) -> None:
    path = order_manager.ORDER_LOG_DIR / "paper_accounting_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"safe": bool(safe), "reason": reason},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def _sync_confirmed_fill_to_reporting() -> bool:
    """確定約定から報告を冪等再生成する。通貨が混在する場合は安全に停止する。

    The legacy report engine is single-currency JPY. Validate the durable fills
    before touching its PnL/equity outputs. A USD IBKR fill is preserved in the
    ledger, but reporting is marked unavailable until explicit FX conversion is
    supplied by a future accounting layer. This function never sends orders.
    """
    try:
        audit_confirmed_accounting_file(
            order_manager.ORDER_LOG_PATH,
            initial_capital=float(TRADING_CAPITAL),
            account_currency="JPY",
        )
    except ConfirmedAccountingCurrencyError as exc:
        _write_accounting_status(safe=False, reason=str(exc))
        return False

    order_manager.save_realized_trade_pnls()
    orders = order_manager.load_accounting_orders()
    equity_points = calculate_equity_curve(orders, initial_capital=float(TRADING_CAPITAL))
    _write_accounting_status(safe=True, reason=None)
    if not equity_points:
        return True
    append_equity_history(
        equity_points[-1],
        order_manager.ORDER_LOG_DIR / "equity_history.csv",
    )
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
    return True


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


def _execute_confirmed_ibkr_paper_order(
    ticker: str,
    signal: str,
    shares: int,
    reference_price: float,
) -> dict:
    normalized_signal = str(signal).upper()
    requested_shares = int(shares)
    if requested_shares <= 0:
        raise RuntimeError("IBKR Paperパイロット注文数量は1以上である必要があります。")

    verified_quantity = verified_paper_test_quantity_for_ticker(ticker)
    if verified_quantity is None:
        raise RuntimeError(
            f"{ticker}: broker-verified Paper pilot quantity is not registered; order blocked."
        )

    instrument = _instrument_for_ticker(ticker)
    normalized_shares = int(verified_quantity)
    order_intent_id = (
        "signal-runner:paper-pilot:"
        f"{ticker}:{normalized_signal}:{normalized_shares}:"
        f"{_paper_signal_session_key(ticker)}"
    )
    execution = execute_approved_signal_via_ibkr_paper(
        ticker=str(ticker),
        signal=normalized_signal,
        shares=normalized_shares,
        order_intent_id=order_intent_id,
        order_log_path=order_manager.ORDER_LOG_PATH,
    )
    result = execution.broker_result
    confirmed = (
        confirmed_fill_from_broker_result(result, normalized_shares)
        if execution.attempted
        else None
    )
    if confirmed is None:
        raise RuntimeError(_describe_unconfirmed_ibkr_result(execution))
    confirmed_quantity, confirmed_price = confirmed
    reporting_safe = _sync_confirmed_fill_to_reporting()
    return {
        "mode": "IBKR_PAPER",
        "ticker": str(ticker),
        "side": normalized_signal,
        "shares": int(confirmed_quantity),
        "reference_price": float(confirmed_price),
        "currency": instrument.currency,
        "status": "FILLED",
        "order_intent_id": order_intent_id,
        "strategy_requested_shares": requested_shares,
        "paper_pilot_shares": normalized_shares,
        "reporting_safe": reporting_safe,
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
    print("IBKR Pilot Qty: broker-verified per instrument")
    print("=" * 50)
    result = run_paper_trading()
    health = evaluate_paper_trading_health(
        signal_count=len(result["records"]),
        error_count=len(result["errors"]),
    )
    print("=" * 50)
    print("IBKR Paper Trading実行結果")
    print(f"診断結果    : {health.status}")
    print(f"状態        : {health.message}")
    print(f"シグナル件数: {health.signal_count}")
    print(f"エラー件数  : {health.error_count}")
    print("=" * 50)


if __name__ == "__main__":
    main()
