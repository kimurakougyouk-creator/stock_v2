"""Explicitly gated Paper-only AAPL position reset for one known legacy mismatch.

This is not a general SELL path. It exists only for the verified state where the
broker holds exactly 3 AAPL shares while the trusted local accounting position is
exactly 1 share because an old AAPL BUY row lacks currency/broker identity.

Safety properties:
- Live Trading must remain disabled.
- Requires an exact human confirmation string.
- Requires broker AAPL quantity == 3 and local AAPL quantity == 1.
- Requires the exact known legacy blocker row and no current AAPL open order.
- Uses an IBKR what-if before one LIMIT/DAY Overnight Paper SELL of exactly 3.
- Acquires a reconciliation pause before transmission so the reset execution
  cannot race into the accounting ledger.
- A confirmed reset execution is written only to the reconciliation exclusion
  registry, never to the accounting ledger.
- The old incomplete AAPL row is quarantined only after the broker proves AAPL
  is flat. Unrelated legacy blockers are left untouched.
- Timeout/uncertain state is never resent automatically; the reconciliation
  pause remains in place for manual evidence review.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import order_manager
from ai_asset_platform.account import Account
from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_aapl_reset_whatif import (
    TARGET_QUANTITY,
    TARGET_SYMBOL,
    preview_aapl_reset_whatif,
)
from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_overnight_paper_e2e import (
    is_ibkr_overnight_session_open,
)
from ai_asset_platform.brokers.ibkr_targeted_legacy_retirement import (
    retire_stale_legacy_ibkr_fill_by_intent,
)
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.broker_position_guard import (
    evaluate_broker_position_guard,
)
from ai_asset_platform.execution.confirmed_fill_evidence import (
    confirmed_fill_from_broker_result,
)
from ai_asset_platform.execution.ibkr_reconciliation_control import (
    ReconciliationControlError,
    acquire_reconciliation_pause,
    record_reconciliation_exclusions,
    release_reconciliation_pause,
)
from ai_asset_platform.execution.ibkr_signal_runtime import (
    _broker_exec_ids,
    _connect_first_available_paper_broker,
)
from ai_asset_platform.execution.service import ExecutionService
from ai_asset_platform.execution.shared_risk_gate import build_shared_risk_gate

TARGET_LEGACY_INTENT = "signal-runner:AAPL:BUY:1:0.00000000"
CONFIRMATION_TEXT = "YES_SELL_EXACTLY_THREE_AAPL_PAPER_TO_FLAT"
RESET_INTENT_ID = "aapl-paper-flat-reset:AAPL:SELL:3:v1"


@dataclass(frozen=True)
class AaplResetPlan:
    ready: bool
    reason: str
    broker_quantity: float
    local_quantity: float | None
    market_price: float | None
    limit_price: float | None


@dataclass(frozen=True)
class AaplFlatResetResult:
    attempted: bool
    reason: str
    plan: AaplResetPlan
    broker_result: object | None
    broker_flat_after: bool
    legacy_retired: bool
    excluded_exec_ids: tuple[str, ...]
    reconciliation_pause_left: bool


def _aapl_position(snapshot: IbkrPaperAccountSnapshot):
    matches = [
        item for item in snapshot.positions
        if str(item.symbol).strip().upper() == TARGET_SYMBOL
        and str(item.sec_type).strip().upper() == "STK"
    ]
    return matches[0] if len(matches) == 1 else None


def _legacy_blocker_present(records: list[dict]) -> bool:
    matches = [
        row for row in records
        if str(row.get("order_intent_id", "")).strip() == TARGET_LEGACY_INTENT
    ]
    if len(matches) != 1:
        return False
    row = matches[0]
    try:
        shares = float(row.get("shares"))
    except (TypeError, ValueError):
        return False
    return (
        str(row.get("mode", "")).strip().upper() == "IBKR_PAPER"
        and str(row.get("status", "")).strip().upper() == "FILLED"
        and str(row.get("ticker", "")).strip().upper() == TARGET_SYMBOL
        and str(row.get("side", "")).strip().upper() == "BUY"
        and shares == 1.0
        and not str(row.get("currency", "")).strip()
        and row.get("broker_order_id") in (None, "")
        and row.get("broker_exec_ids") in (None, "", [], ())
    )


def build_aapl_reset_plan(
    snapshot: IbkrPaperAccountSnapshot,
    *,
    raw_records: list[dict],
    accounting_records: list[dict],
) -> AaplResetPlan:
    if not snapshot.ready or snapshot.order_sent:
        return AaplResetPlan(False, "broker Paper account snapshot is not ready", 0.0, None, None, None)
    if str(snapshot.base_currency).strip().upper() != str(SETTINGS.account_currency).strip().upper():
        return AaplResetPlan(False, "broker base currency does not match configured account currency", 0.0, None, None, None)
    position = _aapl_position(snapshot)
    if position is None:
        return AaplResetPlan(False, "exactly one broker AAPL stock position is required", 0.0, None, None, None)
    broker_qty = float(position.quantity)
    market_price = float(position.market_price)
    guard = evaluate_broker_position_guard(
        ticker=TARGET_SYMBOL,
        side="SELL",
        quantity=TARGET_QUANTITY,
        account=snapshot,
        records=accounting_records,
    )
    local_qty = guard.local_quantity
    if broker_qty != float(TARGET_QUANTITY):
        return AaplResetPlan(False, f"reset requires broker AAPL quantity exactly 3; found {broker_qty:g}", broker_qty, local_qty, market_price if market_price > 0 else None, None)
    if local_qty != 1.0 or guard.allowed or "broker/local position mismatch" not in guard.reason:
        return AaplResetPlan(False, "reset is allowed only for the verified local=1 / broker=3 mismatch", broker_qty, local_qty, market_price if market_price > 0 else None, None)
    if not _legacy_blocker_present(raw_records):
        return AaplResetPlan(False, "the exact identity-less AAPL legacy blocker is not present", broker_qty, local_qty, market_price if market_price > 0 else None, None)
    if market_price <= 0:
        return AaplResetPlan(False, "broker AAPL market price is unavailable", broker_qty, local_qty, None, None)
    limit_price = round(max(0.01, market_price * 0.99), 2)
    return AaplResetPlan(True, "known AAPL Paper mismatch is eligible for a three-share flatten-only reset", broker_qty, local_qty, market_price, limit_price)


def _aapl_open_orders_exist(endpoint_port: int, *, wait_seconds: float = 2.0) -> bool:
    cfg = create_ibkr_paper_config(use_gateway=(int(endpoint_port) == 4002))
    broker = IbkrBrokerAdapter(cfg, enable_paper_order_transmission=False)
    try:
        if not broker.connect(connect_timeout=10.0):
            raise RuntimeError("cannot verify current AAPL open orders")
        client = broker._session.client
        client.reqOpenOrders()
        time.sleep(wait_seconds)
        for row in client.open_orders.values():
            if str(row.get("symbol", "")).strip().upper() == TARGET_SYMBOL:
                return True
        return False
    finally:
        broker.disconnect()


def _broker_flat_after_fill(*, attempts: int = 3, wait_seconds: float = 2.0) -> tuple[bool, IbkrPaperAccountSnapshot]:
    latest = preview_ibkr_paper_account_snapshot()
    for index in range(max(1, attempts)):
        position = _aapl_position(latest)
        quantity = 0.0 if position is None else float(position.quantity)
        if latest.ready and quantity == 0.0:
            return True, latest
        if index + 1 < attempts:
            time.sleep(wait_seconds)
            latest = preview_ibkr_paper_account_snapshot()
    return False, latest


def run_aapl_flat_reset() -> AaplFlatResetResult:
    empty_plan = AaplResetPlan(False, "not evaluated", 0.0, None, None, None)
    if not SETTINGS.enable_paper_trading or not SETTINGS.enable_ibkr_paper:
        return AaplFlatResetResult(False, "IBKR Paper is not explicitly enabled", empty_plan, None, False, False, (), False)
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return AaplFlatResetResult(False, "Live Trading safety lock is not intact", empty_plan, None, False, False, (), False)
    if os.getenv("IBKR_AAPL_RESET_CONFIRM", "").strip() != CONFIRMATION_TEXT:
        return AaplFlatResetResult(False, "exact AAPL Paper reset confirmation is missing", empty_plan, None, False, False, (), False)
    if not is_ibkr_overnight_session_open():
        return AaplFlatResetResult(False, "IBKR Overnight session is closed; no order was attempted", empty_plan, None, False, False, (), False)

    raw_records = list(order_manager.load_paper_orders())
    accounting_records = list(order_manager.load_accounting_orders())
    snapshot = preview_ibkr_paper_account_snapshot()
    plan = build_aapl_reset_plan(
        snapshot,
        raw_records=raw_records,
        accounting_records=accounting_records,
    )
    if not plan.ready or plan.limit_price is None or snapshot.endpoint_port is None:
        return AaplFlatResetResult(False, plan.reason, plan, None, False, False, (), False)

    whatif = preview_aapl_reset_whatif(limit_price=plan.limit_price)
    if not whatif.ready or not whatif.primary_exchange:
        return AaplFlatResetResult(False, "AAPL three-share SELL what-if did not pass", plan, None, False, False, (), False)

    pause = None
    broker_result = None
    attempted = False
    excluded: tuple[str, ...] = ()
    broker_flat = False
    legacy_retired = False
    keep_pause = False
    try:
        pause = acquire_reconciliation_pause(RESET_INTENT_ID)
        if _aapl_open_orders_exist(snapshot.endpoint_port):
            return AaplFlatResetResult(False, "an AAPL open order already exists; reset blocked", plan, None, False, False, (), False)

        instrument = InstrumentSpec(
            symbol=TARGET_SYMBOL,
            asset_class=AssetClass.STOCK,
            exchange="OVERNIGHT",
            currency="USD",
            primary_exchange=whatif.primary_exchange,
            verified_paper_test_quantity=TARGET_QUANTITY,
        )
        order = OrderRequest(
            symbol=TARGET_SYMBOL,
            side=OrderSide.SELL,
            quantity=TARGET_QUANTITY,
            order_type=OrderType.LIMIT,
            limit_price=plan.limit_price,
        )
        broker = _connect_first_available_paper_broker()
        service = ExecutionService(
            broker=broker,
            account=Account(initial_cash=0.0),
            risk_gate=build_shared_risk_gate(),
        )
        try:
            attempted = True
            broker_result = service.execute_ibkr_paper_order(
                order,
                order_intent_id=RESET_INTENT_ID,
                instrument=instrument,
                apply_account_fill=False,
            )
        finally:
            broker.disconnect()

        confirmed = confirmed_fill_from_broker_result(broker_result, TARGET_QUANTITY)
        if confirmed is None:
            keep_pause = bool(getattr(broker_result, "sent", False))
            return AaplFlatResetResult(
                attempted,
                "reset order state is not a confirmed full fill; never resend automatically",
                plan,
                broker_result,
                False,
                False,
                (),
                keep_pause,
            )

        exec_ids = tuple(_broker_exec_ids(broker_result))
        if not exec_ids:
            keep_pause = True
            return AaplFlatResetResult(
                True,
                "confirmed fill lacks broker exec_id; reconciliation remains paused",
                plan,
                broker_result,
                False,
                False,
                (),
                True,
            )
        excluded = record_reconciliation_exclusions(
            exec_ids,
            symbol=TARGET_SYMBOL,
            reason="Paper-only flatten reset for unrecoverable legacy AAPL position mismatch; do not treat as accounting fill",
            order_intent_id=RESET_INTENT_ID,
        )
        broker_flat, post_snapshot = _broker_flat_after_fill()
        if not broker_flat:
            keep_pause = True
            return AaplFlatResetResult(
                True,
                "three-share fill confirmed but broker-flat AAPL state is not yet proven",
                plan,
                broker_result,
                False,
                False,
                excluded,
                True,
            )
        retired = retire_stale_legacy_ibkr_fill_by_intent(
            TARGET_LEGACY_INTENT,
            account=post_snapshot,
        )
        legacy_retired = retired.changed
        if not legacy_retired:
            keep_pause = True
            return AaplFlatResetResult(
                True,
                "broker is flat but targeted legacy retirement did not complete",
                plan,
                broker_result,
                True,
                False,
                excluded,
                True,
            )
        return AaplFlatResetResult(
            True,
            "AAPL Paper reset completed: broker flat, reset execution excluded from accounting reconciliation, legacy row quarantined",
            plan,
            broker_result,
            True,
            True,
            excluded,
            False,
        )
    except ReconciliationControlError as exc:
        keep_pause = pause is not None
        return AaplFlatResetResult(
            attempted,
            f"reconciliation safety control blocked reset: {exc}",
            plan,
            broker_result,
            broker_flat,
            legacy_retired,
            excluded,
            keep_pause,
        )
    finally:
        if pause is not None and not keep_pause:
            release_reconciliation_pause(pause)


def main() -> int:
    result = run_aapl_flat_reset()
    broker_result = result.broker_result
    print("===== IBKR PAPER AAPL THREE-SHARE FLAT RESET =====")
    print("PLAN READY              :", result.plan.ready)
    print("PLAN REASON             :", result.plan.reason)
    print("BROKER AAPL QTY BEFORE  :", result.plan.broker_quantity)
    print("LOCAL AAPL QTY BEFORE   :", result.plan.local_quantity)
    print("BROKER MARKET PRICE     :", result.plan.market_price)
    print("AUTO LIMIT PRICE        :", result.plan.limit_price)
    print("RESET ATTEMPTED         :", result.attempted)
    print("RESET REASON            :", result.reason)
    print("BROKER SENT             :", getattr(broker_result, "sent", False))
    print("BROKER ORDER ID         :", getattr(broker_result, "order_id", None))
    print("BROKER STATUS           :", getattr(broker_result, "status", None))
    print("BROKER FILLED           :", getattr(broker_result, "filled_quantity", 0.0))
    print("BROKER AVG PRICE        :", getattr(broker_result, "avg_fill_price", None))
    print("EXCLUDED EXEC IDS       :", list(result.excluded_exec_ids))
    print("BROKER AAPL FLAT AFTER  :", result.broker_flat_after)
    print("LEGACY AAPL RETIRED     :", result.legacy_retired)
    print("RECONCILIATION PAUSED   :", result.reconciliation_pause_left)
    print("REAL LIVE ORDER SENT    : False")
    if result.broker_flat_after and result.legacy_retired and not result.reconciliation_pause_left:
        return 0
    return 1 if result.attempted else 2


if __name__ == "__main__":
    raise SystemExit(main())
