"""Explicitly gated SPY Overnight Paper SELL used only to close one held share."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import order_manager
from config import STOP_LOSS_RATE, TRADING_CAPITAL
from ai_asset_platform.account import Account
from ai_asset_platform.brokers.ibkr_execution_snapshot import preview_ibkr_paper_execution_snapshot
from ai_asset_platform.brokers.ibkr_overnight_close_whatif import preview_spy_overnight_close_whatif
from ai_asset_platform.brokers.ibkr_overnight_paper_e2e import is_ibkr_overnight_session_open, overnight_session_key
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.broker_position_guard import evaluate_broker_position_guard
from ai_asset_platform.execution.confirmed_fill_evidence import confirmed_fill_from_broker_result
from ai_asset_platform.execution.ibkr_execution_reconcile import reconcile_execution_snapshot_to_ledger
from ai_asset_platform.execution.ibkr_signal_runtime import (
    _broker_exec_ids, _capture_account_fx_rate, _connect_first_available_paper_broker,
)
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
from ai_asset_platform.execution.service import ExecutionService
from ai_asset_platform.execution.shared_risk_gate import build_shared_risk_gate
from ai_asset_platform.execution.verified_paper_preflight import VerifiedPaperPreflightError, evaluate_verified_paper_preflight


@dataclass(frozen=True)
class OvernightPaperCloseResult:
    attempted: bool
    reason: str
    order_intent_id: str | None
    broker_result: object | None
    confirmed_fill_persisted: bool


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def run_spy_overnight_paper_close(*, limit_price: float, order_log_path: Path = Path("results/paper_orders.jsonl"), now: datetime | None = None) -> OvernightPaperCloseResult:
    if not SETTINGS.enable_paper_trading or not SETTINGS.enable_ibkr_paper:
        return OvernightPaperCloseResult(False, "IBKR Paper is not explicitly enabled", None, None, False)
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return OvernightPaperCloseResult(False, "Live Trading safety lock is not intact", None, None, False)
    if not _enabled("AI_ASSET_ENABLE_IBKR_OVERNIGHT_CLOSE_E2E"):
        return OvernightPaperCloseResult(False, "dedicated Overnight close opt-in is disabled", None, None, False)
    if float(limit_price) <= 0:
        raise ValueError("limit_price must be positive")
    if not is_ibkr_overnight_session_open(now):
        return OvernightPaperCloseResult(False, "IBKR Overnight session is closed; no order was attempted", None, None, False)

    snapshot = preview_ibkr_paper_execution_snapshot()
    reconcile = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=order_log_path)
    if not snapshot.ready or reconcile.errors:
        return OvernightPaperCloseResult(False, "broker execution reconciliation is not safe", None, None, False)

    records = order_manager.load_accounting_orders()
    position_guard = evaluate_broker_position_guard(ticker="SPY", side="SELL", quantity=1, records=records)
    if not position_guard.allowed:
        return OvernightPaperCloseResult(False, f"broker position guard blocked: {position_guard.reason}", None, None, False)
    if position_guard.local_quantity != 1 or position_guard.broker_quantity != 1:
        return OvernightPaperCloseResult(False, "SPY close requires exactly one reconciled held share", None, None, False)

    try:
        preflight = evaluate_verified_paper_preflight(
            records=records, ticker="SPY", side="SELL", quantity=1,
            reference_price=float(limit_price), instrument_currency="USD",
            settings=SETTINGS, initial_capital=float(TRADING_CAPITAL),
            fx_to_account_rate=None, stop_loss_rate=float(STOP_LOSS_RATE),
        )
    except VerifiedPaperPreflightError as exc:
        return OvernightPaperCloseResult(False, f"SELL preflight failed: {exc}", None, None, False)
    if not preflight.allowed:
        return OvernightPaperCloseResult(False, preflight.reason, None, None, False)

    whatif = preview_spy_overnight_close_whatif(limit_price=float(limit_price))
    if not whatif.ready or not whatif.primary_exchange:
        return OvernightPaperCloseResult(False, "Overnight SELL what-if did not pass", None, None, False)

    intent_id = f"overnight-paper-e2e:SPY:SELL:1:{overnight_session_key(now)}"
    instrument = InstrumentSpec(
        symbol="SPY", asset_class=AssetClass.ETF, exchange="OVERNIGHT", currency="USD",
        primary_exchange=whatif.primary_exchange, verified_paper_test_quantity=1,
    )
    order = OrderRequest(symbol="SPY", side=OrderSide.SELL, quantity=1, order_type=OrderType.LIMIT, limit_price=float(limit_price))
    broker = _connect_first_available_paper_broker()
    service = ExecutionService(broker=broker, account=Account(initial_cash=0.0), risk_gate=build_shared_risk_gate())
    try:
        result = service.execute_ibkr_paper_order(order, order_intent_id=intent_id, instrument=instrument, apply_account_fill=False)
        confirmed = confirmed_fill_from_broker_result(result, 1)
        persisted = False
        if confirmed is not None:
            quantity, price = confirmed
            fx_rate = _capture_account_fx_rate("USD")
            raw_order_id = getattr(result, "order_id", None)
            record_confirmed_fill(
                ticker="SPY", side="SELL", filled_quantity=quantity, avg_fill_price=price,
                currency="USD", order_intent_id=intent_id, order_log_path=order_log_path,
                fx_to_account_rate=fx_rate, broker_exec_ids=_broker_exec_ids(result),
                broker_order_id=int(raw_order_id) if raw_order_id is not None else None,
            )
            persisted = True
        return OvernightPaperCloseResult(True, "Paper position-reducing SELL attempted once; broker result observed only", intent_id, result, persisted)
    finally:
        broker.disconnect()


def main() -> int:
    raw = os.getenv("IBKR_OVERNIGHT_CLOSE_LIMIT_PRICE", "").strip()
    if not raw:
        print("IBKR_OVERNIGHT_CLOSE_LIMIT_PRICE is required. No order was sent.")
        return 2
    try:
        price = float(raw)
    except ValueError:
        print("IBKR_OVERNIGHT_CLOSE_LIMIT_PRICE must be numeric. No order was sent.")
        return 2
    result = run_spy_overnight_paper_close(limit_price=price)
    broker_result = result.broker_result
    print("===== IBKR PAPER OVERNIGHT SPY CLOSE =====")
    print("ATTEMPTED              :", result.attempted)
    print("REASON                 :", result.reason)
    print("ORDER INTENT ID        :", result.order_intent_id)
    print("CONFIRMED FILL PERSISTED:", result.confirmed_fill_persisted)
    print("BROKER STATUS          :", getattr(broker_result, "status", None))
    print("BROKER SENT            :", getattr(broker_result, "sent", False))
    print("BROKER ORDER ID        :", getattr(broker_result, "order_id", None))
    print("BROKER FILLED          :", getattr(broker_result, "filled_quantity", 0.0))
    print("BROKER AVG PRICE       :", getattr(broker_result, "avg_fill_price", None))
    print("REAL LIVE ORDER SENT   : False")
    return 0 if result.confirmed_fill_persisted else (1 if result.attempted else 2)


if __name__ == "__main__":
    raise SystemExit(main())
