"""Explicitly gated SPY Overnight Paper E2E pilot.

This module can submit one real *Paper* order only when every gate is satisfied:
- general IBKR Paper opt-in is enabled for the process;
- a dedicated Overnight E2E opt-in is enabled;
- the official Overnight session is currently open in America/New_York;
- the integrated non-order operator checkpoint passes (what-if, broker FX
  evidence, accounting, confirmed holdings, allocation/risk/daily-notional);
- the shared Risk Gate still allows the final request.

The order is LIMIT/DAY, quantity 1, and uses a durable session-scoped intent id.
Timeout or uncertain state is never automatically resent. Live Trading is not
implemented here. A confirmed cross-currency fill persists the exact FX evidence
used by the checkpoint so account-currency accounting remains reproducible.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_asset_platform.account import Account
from ai_asset_platform.brokers.ibkr_operator_checkpoint import (
    run_ibkr_operator_checkpoint,
)
from ai_asset_platform.brokers.ibkr_overnight_whatif import IbkrOvernightWhatIfResult
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.ibkr_signal_runtime import (
    _confirmed_fill_from_broker_result,
    _connect_first_available_paper_broker,
)
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill
from ai_asset_platform.execution.service import ExecutionService
from ai_asset_platform.execution.shared_risk_gate import build_shared_risk_gate

_ET = ZoneInfo("America/New_York")
_OVERNIGHT_START = time(20, 0)
_OVERNIGHT_END = time(3, 50)


@dataclass(frozen=True)
class OvernightPaperE2EResult:
    attempted: bool
    reason: str
    order_intent_id: str | None
    whatif: IbkrOvernightWhatIfResult | None
    broker_result: object | None
    confirmed_fill_persisted: bool


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_ibkr_overnight_session_open(now: datetime | None = None) -> bool:
    """Return whether the documented US Overnight session is open."""
    current = now.astimezone(_ET) if now is not None else datetime.now(_ET)
    weekday = current.weekday()
    clock = current.timetz().replace(tzinfo=None)

    if weekday in {6, 0, 1, 2, 3} and clock >= _OVERNIGHT_START:
        return True
    if weekday in {0, 1, 2, 3, 4} and clock < _OVERNIGHT_END:
        return True
    return False


def overnight_session_key(now: datetime | None = None) -> str:
    """Stable key for the current Overnight session start date in ET."""
    current = now.astimezone(_ET) if now is not None else datetime.now(_ET)
    clock = current.timetz().replace(tzinfo=None)
    session_start_date = (
        current.date() - timedelta(days=1)
        if clock < _OVERNIGHT_END
        else current.date()
    )
    return session_start_date.isoformat()


def run_spy_overnight_paper_e2e(
    *,
    limit_price: float,
    order_log_path: Path = Path("results/paper_orders.jsonl"),
    now: datetime | None = None,
) -> OvernightPaperE2EResult:
    """Submit at most one explicitly approved SPY Overnight Paper pilot per session."""
    if not SETTINGS.enable_paper_trading or not SETTINGS.enable_ibkr_paper:
        return OvernightPaperE2EResult(
            False, "IBKR Paper is not explicitly enabled for this process", None, None, None, False
        )
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return OvernightPaperE2EResult(
            False, "Live Trading safety lock is not intact", None, None, None, False
        )
    if not _env_enabled("AI_ASSET_ENABLE_IBKR_OVERNIGHT_E2E"):
        return OvernightPaperE2EResult(
            False, "dedicated Overnight Paper E2E opt-in is disabled", None, None, None, False
        )
    if float(limit_price) <= 0:
        raise ValueError("limit_price must be positive")
    if not is_ibkr_overnight_session_open(now):
        return OvernightPaperE2EResult(
            False, "IBKR Overnight session is closed; no order was attempted", None, None, None, False
        )

    # One integrated, non-real-order gate immediately before transmission.
    # This includes what-if, explicit broker FX evidence, durable accounting,
    # existing-position detection and verified account-currency preflight.
    checkpoint = run_ibkr_operator_checkpoint(limit_price=float(limit_price))
    whatif = checkpoint.whatif
    if not checkpoint.ready_for_paper_e2e_review:
        reason = checkpoint.preflight_error or checkpoint.accounting_error or "operator checkpoint did not pass"
        return OvernightPaperE2EResult(False, reason, None, whatif, None, False)
    if checkpoint.fx is None or not checkpoint.fx.ready or checkpoint.fx.rate is None:
        return OvernightPaperE2EResult(
            False, "operator checkpoint has no usable FX evidence", None, whatif, None, False
        )
    if not whatif.ready or not whatif.primary_exchange:
        return OvernightPaperE2EResult(
            False, "Overnight server-side what-if did not pass", None, whatif, None, False
        )

    intent_id = f"overnight-paper-e2e:SPY:BUY:1:{overnight_session_key(now)}"
    instrument = InstrumentSpec(
        symbol="SPY",
        asset_class=AssetClass.ETF,
        exchange="OVERNIGHT",
        currency="USD",
        primary_exchange=whatif.primary_exchange,
        verified_paper_test_quantity=1,
    )
    order = OrderRequest(
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=float(limit_price),
    )

    broker = _connect_first_available_paper_broker()
    service = ExecutionService(
        broker=broker,
        account=Account(initial_cash=0.0),
        risk_gate=build_shared_risk_gate(),
    )
    try:
        broker_result = service.execute_ibkr_paper_order(
            order,
            order_intent_id=intent_id,
            instrument=instrument,
            apply_account_fill=False,
        )
        confirmed = _confirmed_fill_from_broker_result(broker_result, 1)
        persisted = False
        if confirmed is not None:
            quantity, price = confirmed
            record_confirmed_fill(
                ticker="SPY",
                side="BUY",
                filled_quantity=quantity,
                avg_fill_price=price,
                currency=instrument.currency,
                order_intent_id=intent_id,
                order_log_path=order_log_path,
                fx_to_account_rate=float(checkpoint.fx.rate),
            )
            persisted = True
        return OvernightPaperE2EResult(
            True,
            "Paper order attempted once; result is broker-observed only",
            intent_id,
            whatif,
            broker_result,
            persisted,
        )
    finally:
        broker.disconnect()
