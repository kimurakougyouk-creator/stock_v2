"""Explicitly gated SPY extended-hours Paper SELL used only to close one held share.

This path is position-reducing only. It requires exactly one reconciled SPY
share, verifies the broker account, obtains a SMART OutsideRth SELL what-if, and
may submit one LIMIT/DAY Paper SELL behind a dedicated opt-in. Live Trading is
prohibited and timeout/uncertain results are never retried automatically.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import order_manager
from config import STOP_LOSS_RATE, TRADING_CAPITAL
from ai_asset_platform.account import Account
from ai_asset_platform.brokers.ibkr_execution_snapshot import preview_ibkr_paper_execution_snapshot
from ai_asset_platform.brokers.ibkr_extended_close_whatif import preview_spy_extended_close_whatif
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.broker_position_guard import evaluate_broker_position_guard
from ai_asset_platform.execution.confirmed_fill_evidence import confirmed_fill_from_broker_result
from ai_asset_platform.execution.ibkr_execution_reconcile import reconcile_execution_snapshot_to_ledger
from ai_asset_platform.execution.ibkr_signal_runtime import (
    _broker_exec_ids,
    _capture_account_fx_rate,
    _connect_first_available_paper_broker,
)
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
from ai_asset_platform.execution.service import ExecutionService
from ai_asset_platform.execution.shared_risk_gate import build_shared_risk_gate
from ai_asset_platform.execution.verified_paper_preflight import (
    VerifiedPaperPreflightError,
    evaluate_verified_paper_preflight,
)

_ET = ZoneInfo("America/New_York")
_PREMARKET_START = time(4, 0)
_RTH_START = time(9, 30)
_RTH_END = time(16, 0)
_AFTER_HOURS_END = time(20, 0)


@dataclass(frozen=True)
class ExtendedPaperCloseResult:
    attempted: bool
    reason: str
    order_intent_id: str | None
    broker_result: object | None
    confirmed_fill_persisted: bool


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_us_extended_session_open(now: datetime | None = None) -> bool:
    current = now.astimezone(_ET) if now is not None else datetime.now(_ET)
    if current.weekday() > 4:
        return False
    clock = current.timetz().replace(tzinfo=None)
    return (_PREMARKET_START <= clock < _RTH_START) or (_RTH_END <= clock < _AFTER_HOURS_END)


def extended_session_key(now: datetime | None = None) -> str:
    current = now.astimezone(_ET) if now is not None else datetime.now(_ET)
    return current.strftime("%Y-%m-%d-%H")


def run_spy_extended_paper_close(
    *,
    limit_price: float,
    order_log_path: Path = Path("results/paper_orders.jsonl"),
    now: datetime | None = None,
) -> ExtendedPaperCloseResult:
    if not SETTINGS.enable_paper_trading or not SETTINGS.enable_ibkr_paper:
        return ExtendedPaperCloseResult(False, "IBKR Paper is not explicitly enabled", None, None, False)
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return ExtendedPaperCloseResult(False, "Live Trading safety lock is not intact", None, None, False)
    if not _enabled("AI_ASSET_ENABLE_IBKR_EXTENDED_CLOSE_E2E"):
        return ExtendedPaperCloseResult(False, "dedicated extended-hours close opt-in is disabled", None, None, False)
    if float(limit_price) <= 0:
        raise ValueError("limit_price must be positive")
    if not is_us_extended_session_open(now):
        return ExtendedPaperCloseResult(False, "US extended-hours session is closed; no order was attempted", None, None, False)

    snapshot = preview_ibkr_paper_execution_snapshot()
    reconcile = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=order_log_path)
    if not snapshot.ready or reconcile.errors:
        return ExtendedPaperCloseResult(False, "broker execution reconciliation is not safe", None, None, False)

    records = order_manager.load_accounting_orders()
    position_guard = evaluate_broker_position_guard(
        ticker="SPY", side="SELL", quantity=1, records=records,
    )
    if not position_guard.allowed:
        return ExtendedPaperCloseResult(False, f"broker position guard blocked: {position_guard.reason}", None, None, False)
    if position_guard.local_quantity != 1 or position_guard.broker_quantity != 1:
        return ExtendedPaperCloseResult(False, "SPY close requires exactly one reconciled held share", None, None, False)

    try:
        preflight = evaluate_verified_paper_preflight(
            records=records,
            ticker="SPY",
            side="SELL",
            quantity=1,
            reference_price=float(limit_price),
            instrument_currency="USD",
            settings=SETTINGS,
            initial_capital=float(TRADING_CAPITAL),
            fx_to_account_rate=None,
            stop_loss_rate=float(STOP_LOSS_RATE),
        )
    except VerifiedPaperPreflightError as exc:
        return ExtendedPaperCloseResult(False, f"SELL preflight failed: {exc}", None, None, False)
    if not preflight.allowed:
        return ExtendedPaperCloseResult(False, preflight.reason, None, None, False)

    whatif = preview_spy_extended_close_whatif(limit_price=float(limit_price))
    if not whatif.ready:
        return ExtendedPaperCloseResult(False, "extended-hours SELL what-if did not pass", None, None, False)

    intent_id = f"extended-paper-close:SPY:SELL:1:{extended_session_key(now)}"
    instrument = InstrumentSpec(
        symbol="SPY",
        asset_class=AssetClass.ETF,
        exchange="SMART",
        currency="USD",
        primary_exchange=whatif.primary_exchange,
        verified_paper_test_quantity=1,
    )
    order = OrderRequest(
        symbol="SPY",
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=float(limit_price),
        outside_rth=True,
    )
    broker = _connect_first_available_paper_broker()
    service = ExecutionService(
        broker=broker, account=Account(initial_cash=0.0), risk_gate=build_shared_risk_gate()
    )
    try:
        result = service.execute_ibkr_paper_order(
            order, order_intent_id=intent_id, instrument=instrument, apply_account_fill=False
        )
        confirmed = confirmed_fill_from_broker_result(result, 1)
        persisted = False
        if confirmed is not None:
            quantity, price = confirmed
            fx_rate = _capture_account_fx_rate("USD")
            raw_order_id = getattr(result, "order_id", None)
            record_confirmed_fill(
                ticker="SPY",
                side="SELL",
                filled_quantity=quantity,
                avg_fill_price=price,
                currency="USD",
                order_intent_id=intent_id,
                order_log_path=order_log_path,
                fx_to_account_rate=fx_rate,
                broker_exec_ids=_broker_exec_ids(result),
                broker_order_id=int(raw_order_id) if raw_order_id is not None else None,
            )
            persisted = True
        return ExtendedPaperCloseResult(
            True,
            "Paper position-reducing extended-hours SELL attempted once; broker result observed only",
            intent_id,
            result,
            persisted,
        )
    finally:
        broker.disconnect()
