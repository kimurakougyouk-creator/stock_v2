"""Paper Trading専用ランナー。"""
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import STOP_LOSS_RATE, TRADING_CAPITAL
from ai_asset_platform.brokers.ibkr_fx_evidence import resolve_ibkr_paper_fx_evidence
from ai_asset_platform.core.account_clock import account_now
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.confirmed_fill_evidence import (
    confirmed_fill_from_broker_result,
)
from ai_asset_platform.execution.ibkr_signal_runtime import execute_approved_signal_via_ibkr_paper
from ai_asset_platform.execution.paper_trading_loop import run_paper_trading_loop
from ai_asset_platform.execution.signal_order_bridge import (
    _instrument_for_ticker,
    verified_paper_test_quantity_for_ticker,
    verified_paper_tickers,
)
from ai_asset_platform.execution.verified_market_session import (
    evaluate_verified_market_session,
)
from ai_asset_platform.execution.verified_paper_preflight import (
    VerifiedPaperPreflightError,
    evaluate_verified_paper_preflight,
)
from ai_asset_platform.execution.verified_paper_scan import (
    classify_paper_execution_error,
    execute_verified_actions_from_scan,
)
from ai_asset_platform.reports.equity_history import (
    append_equity_history,
    calculate_maximum_drawdown,
)
from ai_asset_platform.reports.multicurrency_confirmed_accounting import (
    MulticurrencyConfirmedAccountingError,
    audit_multicurrency_confirmed_accounting,
    calculate_multicurrency_equity_curve,
)
from ai_asset_platform.reports.multicurrency_trade_history import (
    MulticurrencyTradeHistoryError,
    calculate_realized_trade_history,
)
from ai_asset_platform.reports.paper_trading_health import evaluate_paper_trading_health
from ai_asset_platform.execution import order_manager
import signal_runner


_US_ET = ZoneInfo("America/New_York")
_JST = ZoneInfo("Asia/Tokyo")


def _paper_signal_session_key(ticker: str, now: datetime | None = None) -> str:
    zone = _JST if str(ticker).strip().upper().endswith(".T") else _US_ET
    current = now.astimezone(zone) if now is not None else datetime.now(zone)
    return current.date().isoformat()


def _write_accounting_status(*, safe: bool, reason: str | None) -> None:
    path = order_manager.ORDER_LOG_DIR / "paper_accounting_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"safe": bool(safe), "reason": reason}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_multicurrency_summary(summary, *, cross_currency: bool) -> None:
    path = order_manager.ORDER_LOG_DIR / "paper_accounting_summary.json"
    payload = {
        "account_currency": summary.account_currency,
        "cross_currency": bool(cross_currency),
        "confirmed_fill_count": summary.confirmed_fill_count,
        "equity_point_count": summary.equity_point_count,
        "ending_cash": summary.ending_cash,
        "ending_holdings": summary.ending_holdings,
        "ending_equity": summary.ending_equity,
        "realized_pnl": summary.realized_pnl,
        "unrealized_pnl": summary.unrealized_pnl,
        "maximum_drawdown": summary.maximum_drawdown,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_account_currency_trade_history(trades, *, account_currency: str) -> None:
    path = order_manager.ORDER_LOG_DIR / "paper_trade_pnls_account_currency.json"
    records = [trade.as_record() for trade in trades]
    payload = {
        "updated_at": account_now().isoformat(timespec="seconds"),
        "account_currency": account_currency,
        "realized_trade_pnls": [record["realized_pnl_account"] for record in records],
        "realized_trades": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sync_confirmed_fill_to_reporting() -> bool:
    """Rebuild account-currency PnL/equity/drawdown from confirmed evidence."""
    orders = order_manager.load_accounting_orders()
    account_currency = str(SETTINGS.account_currency).strip().upper()
    try:
        points = calculate_multicurrency_equity_curve(
            orders,
            initial_capital=float(TRADING_CAPITAL),
            account_currency=account_currency,
        )
        summary = audit_multicurrency_confirmed_accounting(
            orders,
            initial_capital=float(TRADING_CAPITAL),
            account_currency=account_currency,
        )
        realized_trades = calculate_realized_trade_history(
            orders,
            account_currency=account_currency,
        )
    except (MulticurrencyConfirmedAccountingError, MulticurrencyTradeHistoryError) as exc:
        _write_accounting_status(safe=False, reason=str(exc))
        return False

    cross_currency = any(
        str(order.get("currency", "")).strip().upper() not in {"", account_currency}
        for order in orders
        if isinstance(order, dict)
    )
    if not cross_currency:
        order_manager.save_realized_trade_pnls()

    _write_account_currency_trade_history(realized_trades, account_currency=account_currency)
    _write_multicurrency_summary(summary, cross_currency=cross_currency)
    _write_accounting_status(safe=True, reason=None)
    if not points:
        return True

    append_equity_history(points[-1], order_manager.ORDER_LOG_DIR / "equity_history.csv")
    drawdown_path = order_manager.ORDER_LOG_DIR / "paper_drawdown.json"
    drawdown_path.parent.mkdir(parents=True, exist_ok=True)
    drawdown_path.write_text(
        json.dumps(
            {
                "maximum_drawdown": float(calculate_maximum_drawdown(points)),
                "equity_points": len(points),
                "account_currency": account_currency,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return True


RAW_EXECUTION_DIAGNOSTICS_PATH = Path("results") / "paper_execution_raw_diagnostics.jsonl"

# Only these IBKR result fields are ever persisted; a key not in this list
# (e.g. "message", which carries free-text broker/account content) is never
# captured, even if it appears in the raw error text.
_SAFE_DIAGNOSTIC_FIELD_PATTERN = re.compile(
    r"\b(status|sent|order_id|terminal|timeout|ib_status|filled|avg_price)=([^/]*)"
)
_BROKER_ERROR_CODE_PATTERN = re.compile(r"'code':\s*(\d+)")
# IBKR account ids look like one or two letters followed by 6-9 digits
# (e.g. DU1234567). Redacted even from the bounded leftover note below.
_ACCOUNT_ID_PATTERN = re.compile(r"\b[A-Za-z]{1,2}\d{6,9}\b")
# Any other long alphanumeric run (API keys, tokens, session ids) is treated
# as a potential credential and redacted the same way.
_LONG_TOKEN_PATTERN = re.compile(r"\b[A-Za-z0-9_\-]{16,}\b")
_SAFE_NOTE_MAX_LENGTH = 200


def _structured_execution_diagnostic(raw_error: str) -> dict:
    """Reduce raw_error text to a safe, structured diagnostic.

    Only an allowlisted set of IBKR result fields and numeric broker error
    codes are kept verbatim. Anything else -- including any broker/account
    free text such as "message=" or "errors=[...]" payloads -- is dropped
    rather than persisted. A short leftover note is kept for non-IBKR
    (preflight/FX/connection) reasons, but is first stripped of every
    recognized field/value pair, then of anything shaped like an account id
    or a long token, and finally length-capped.
    """
    text = str(raw_error)
    fields = {
        key: value.strip()
        for key, value in _SAFE_DIAGNOSTIC_FIELD_PATTERN.findall(text)
    }
    error_codes = sorted({int(code) for code in _BROKER_ERROR_CODE_PATTERN.findall(text)})

    # Drop every "key=value" style segment -- not only the allowlisted ones --
    # so an unrecognized key (e.g. "message=...") never leaks into the note.
    note = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*=\[[^\]]*\]", "", text)
    note = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*=[^/]*", "", note)
    note = _ACCOUNT_ID_PATTERN.sub("[ACCOUNT_REDACTED]", note)
    note = _LONG_TOKEN_PATTERN.sub("[TOKEN_REDACTED]", note)
    note = re.sub(r"\s*/\s*/\s*", " / ", note).strip(" /")
    note = note[:_SAFE_NOTE_MAX_LENGTH]

    diagnostic: dict = {"fields": fields}
    if error_codes:
        diagnostic["error_codes"] = error_codes
    if note:
        diagnostic["note"] = note
    return diagnostic


def _record_execution_diagnostic(ticker: str, raw_error: str) -> None:
    """Persist a safe, structured diagnostic derived from the execution-error
    text that classify_paper_execution_error() discards before printing, so a
    future UNKNOWN_ERROR/BROKER_FILL_UNCONFIRMED occurrence can actually be
    root-caused -- without ever persisting the raw error text, an account
    identifier, or anything shaped like a credential/token.

    Never printed to stdout/the autopilot log -- file-only, append-only. Must
    never raise: a diagnostics-write failure must not fail the trading run.
    """
    try:
        diagnostic = _structured_execution_diagnostic(raw_error)
        RAW_EXECUTION_DIAGNOSTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with RAW_EXECUTION_DIAGNOSTICS_PATH.open("a", encoding="utf-8") as file:
            file.write(
                json.dumps(
                    {
                        "recorded_at": account_now().isoformat(),
                        "ticker": ticker,
                        **diagnostic,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass


def _describe_unconfirmed_ibkr_result(execution) -> str:
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
    return "IBKR PaperでFilledを確認できなかったため、注文済みとして記録しません。" + " / ".join(details)


def _preflight_fx_rate(*, instrument_currency: str, side: str) -> float | None:
    """Get broker-only FX evidence only when a new BUY needs account valuation."""
    if str(side).upper() == "SELL":
        return None
    account_currency = str(SETTINGS.account_currency).strip().upper()
    instrument_currency = str(instrument_currency).strip().upper()
    if instrument_currency == account_currency:
        return 1.0
    evidence = resolve_ibkr_paper_fx_evidence(
        base_currency=instrument_currency,
        quote_currency=account_currency,
    )
    if not evidence.ready or evidence.rate is None or float(evidence.rate) <= 0:
        raise RuntimeError(
            f"{instrument_currency}->{account_currency} broker FX evidence is unavailable; BUY blocked"
        )
    return float(evidence.rate)


def _execute_confirmed_ibkr_paper_order(
    ticker: str,
    signal: str,
    shares: int,
    reference_price: float,
    process_start_source_sha: str | None = None,
    strategy_parameters_sha: str | None = None,
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

    session = evaluate_verified_market_session(ticker)
    if not session.allowed:
        raise RuntimeError(
            "verified Paper market-session guard blocked order: "
            f"{session.reason} / venue={session.venue} / "
            f"local={session.local_timestamp}"
        )

    instrument = _instrument_for_ticker(ticker)
    normalized_shares = int(verified_quantity)
    fx_rate = _preflight_fx_rate(
        instrument_currency=instrument.currency,
        side=normalized_signal,
    )
    try:
        preflight = evaluate_verified_paper_preflight(
            records=order_manager.load_accounting_orders(),
            ticker=str(ticker),
            side=normalized_signal,
            quantity=normalized_shares,
            reference_price=float(reference_price),
            instrument_currency=instrument.currency,
            settings=SETTINGS,
            initial_capital=float(TRADING_CAPITAL),
            fx_to_account_rate=fx_rate,
            stop_loss_rate=float(STOP_LOSS_RATE),
        )
    except VerifiedPaperPreflightError as exc:
        raise RuntimeError(f"verified Paper preflight failed: {exc}") from exc
    if not preflight.allowed:
        raise RuntimeError(f"verified Paper preflight blocked order: {preflight.reason}")

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
        process_start_source_sha=process_start_source_sha,
        strategy_parameters_sha=strategy_parameters_sha,
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
        "preflight_fx_to_account_rate": fx_rate,
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
    scan_result = signal_runner.run_signal_scan(
        tickers=list(verified_paper_tickers()),
        ai_provider=ai_provider,
        allow_orders=False,
        allow_email=False,
    )
    return execute_verified_actions_from_scan(
        scan_result,
        execute_order=_execute_confirmed_ibkr_paper_order,
        settings=SETTINGS,
    )


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
    for entry in result.get("execution_errors") or []:
        if not isinstance(entry, dict):
            continue
        ticker = entry.get("ticker", "UNKNOWN")
        raw_error = entry.get("error", "")
        label = classify_paper_execution_error(raw_error)
        _record_execution_diagnostic(ticker, raw_error)
        print(f"  - {ticker}: {label}")
    print("=" * 50)


if __name__ == "__main__":
    main()
