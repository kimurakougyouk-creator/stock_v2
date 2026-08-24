"""Fail-closed Paper-only close for the already-controlled 9432/TSEJ position.

This is deliberately not a general Japan-stock SELL path. It may only reduce
exactly the known controlled Paper position (9432/TSEJ/JPY, 100 shares) to zero.
It requires broker/local agreement, the known BUY execution identity, broker
ContractDetails/lot evidence, an open liquid session, a successful what-if,
no current 9432 open order, and an exact human confirmation string.

A sent order is never automatically resent after timeout/uncertainty. After a
confirmed full fill the broker must prove flat and the broker execution is then
reconciled into the durable local ledger; both broker and local quantities must
be zero before this flow reports success. Live Trading remains prohibited.
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import order_manager
from ai_asset_platform.account import Account
from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_9432_close_whatif import preview_9432_close_whatif
from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_execution_snapshot import preview_ibkr_paper_execution_snapshot
from ai_asset_platform.brokers.ibkr_global_stock_discovery import (
    IbkrGlobalStockCandidate,
    discover_ibkr_paper_global_stock,
)
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass
from ai_asset_platform.core.settings import SETTINGS
from ai_asset_platform.execution.broker_position_guard import evaluate_broker_position_guard
from ai_asset_platform.execution.confirmed_fill_evidence import confirmed_fill_from_broker_result
from ai_asset_platform.execution.ibkr_execution_reconcile import reconcile_execution_snapshot_to_ledger
from ai_asset_platform.execution.ibkr_signal_runtime import _broker_exec_ids, _connect_first_available_paper_broker
from ai_asset_platform.execution.service import ExecutionService
from ai_asset_platform.execution.shared_risk_gate import build_shared_risk_gate

SYMBOL = "9432"
EXCHANGE = "TSEJ"
CURRENCY = "JPY"
QUANTITY = 100
KNOWN_BUY_ORDER_ID = 6
KNOWN_BUY_EXEC_ID = "0000f0df.6a8b7328.01.01"
CONFIRMATION_TEXT = "YES_SELL_EXACTLY_100_9432_TSEJ_PAPER_TO_FLAT"
CLOSE_INTENT_ID = "9432-paper-flat-close:9432:SELL:100:v1"


@dataclass(frozen=True)
class Close9432Plan:
    ready: bool
    reason: str
    broker_quantity: float
    local_quantity: float | None
    market_price: float | None
    limit_price: float | None
    endpoint_port: int | None
    liquid_hours: str | None = None
    time_zone_id: str | None = None


@dataclass(frozen=True)
class Close9432Result:
    attempted: bool
    reason: str
    plan: Close9432Plan
    broker_result: object | None
    broker_flat_after: bool
    local_flat_after: bool
    reconciled_count: int
    close_exec_ids: tuple[str, ...]


def _stock_position(snapshot: IbkrPaperAccountSnapshot):
    matches = [
        item for item in snapshot.positions
        if str(item.symbol).strip().upper() == SYMBOL
        and str(item.sec_type).strip().upper() == "STK"
    ]
    return matches[0] if len(matches) == 1 else None


def _known_buy_is_trusted(records: list[dict]) -> bool:
    for row in records:
        if not isinstance(row, dict):
            continue
        if str(row.get("status", "")).strip().upper() != "FILLED":
            continue
        if str(row.get("ticker", "")).strip().upper() != SYMBOL:
            continue
        if str(row.get("side", "")).strip().upper() != "BUY":
            continue
        if str(row.get("currency", "")).strip().upper() != CURRENCY:
            continue
        try:
            shares = float(row.get("shares"))
        except (TypeError, ValueError):
            continue
        ids = {str(value or "").strip() for value in list(row.get("broker_exec_ids") or [])}
        order_id = row.get("broker_order_id")
        try:
            order_id_value = int(order_id) if order_id not in (None, "") else None
        except (TypeError, ValueError):
            order_id_value = None
        if shares == float(QUANTITY) and KNOWN_BUY_EXEC_ID in ids and order_id_value == KNOWN_BUY_ORDER_ID:
            return True
    return False


def _candidate_is_exact(candidate: IbkrGlobalStockCandidate) -> bool:
    if str(candidate.symbol).strip().upper() != SYMBOL:
        return False
    if str(candidate.exchange).strip().upper() != EXCHANGE:
        return False
    if str(candidate.currency).strip().upper() != CURRENCY:
        return False
    if candidate.con_id is None or int(candidate.con_id) <= 0:
        return False
    if candidate.min_tick is None or float(candidate.min_tick) <= 0:
        return False
    if candidate.min_size is None or abs(float(candidate.min_size) - QUANTITY) > 1e-9:
        return False
    increments = [candidate.size_increment, candidate.suggested_size_increment]
    observed = [float(value) for value in increments if value is not None]
    if not observed or any(value <= 0 for value in observed):
        return False
    if not any(abs(value - QUANTITY) <= 1e-9 for value in observed):
        return False
    order_types = {part.strip().upper() for part in str(candidate.order_types or "").split(",") if part.strip()}
    return "LMT" in order_types


def _zone(name: str | None) -> ZoneInfo | None:
    normalized = str(name or "").strip()
    aliases = {"JAPAN": "Asia/Tokyo", "JST": "Asia/Tokyo"}
    normalized = aliases.get(normalized.upper(), normalized)
    if not normalized:
        return None
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        return None


def _parse_session_endpoint(text: str, default_date: str) -> datetime | None:
    value = str(text).strip()
    if not value:
        return None
    if ":" in value:
        date_text, time_text = value.split(":", 1)
    else:
        date_text, time_text = default_date, value
    try:
        return datetime.strptime(date_text + time_text, "%Y%m%d%H%M")
    except ValueError:
        return None


def liquid_session_is_open(
    candidate: IbkrGlobalStockCandidate,
    *,
    now: datetime | None = None,
) -> bool:
    zone = _zone(candidate.time_zone_id)
    hours = str(candidate.liquid_hours or "").strip()
    if zone is None or not hours:
        return False
    current = (now or datetime.now(timezone.utc)).astimezone(zone)
    for segment in hours.split(";"):
        segment = segment.strip()
        if not segment or "CLOSED" in segment.upper() or ":" not in segment:
            continue
        date_text, intervals_text = segment.split(":", 1)
        for interval in intervals_text.split(","):
            if "-" not in interval:
                continue
            start_text, end_text = interval.split("-", 1)
            start = _parse_session_endpoint(start_text, date_text)
            end = _parse_session_endpoint(end_text, date_text)
            if start is None or end is None:
                continue
            start = start.replace(tzinfo=zone)
            end = end.replace(tzinfo=zone)
            if start <= current < end:
                return True
    return False


def _limit_price(market_price: float, min_tick: float) -> float:
    raw = float(market_price) * 0.99
    tick = float(min_tick)
    ticks = math.floor((raw + 1e-12) / tick)
    return max(tick, round(ticks * tick, 10))


def build_9432_close_plan(
    snapshot: IbkrPaperAccountSnapshot,
    *,
    accounting_records: list[dict],
    discovery,
    now: datetime | None = None,
) -> Close9432Plan:
    if not snapshot.ready or snapshot.order_sent:
        return Close9432Plan(False, "broker Paper account snapshot is not ready", 0.0, None, None, None, snapshot.endpoint_port)
    if str(snapshot.base_currency).strip().upper() != CURRENCY:
        return Close9432Plan(False, "9432 close requires the verified JPY Paper account", 0.0, None, None, None, snapshot.endpoint_port)
    position = _stock_position(snapshot)
    if position is None:
        return Close9432Plan(False, "exactly one broker 9432 stock position is required", 0.0, None, None, None, snapshot.endpoint_port)
    broker_qty = float(position.quantity)
    market_price = float(position.market_price)
    guard = evaluate_broker_position_guard(
        ticker=SYMBOL,
        side="SELL",
        quantity=QUANTITY,
        account=snapshot,
        records=accounting_records,
    )
    if broker_qty != float(QUANTITY):
        return Close9432Plan(False, f"close requires broker 9432 quantity exactly 100; found {broker_qty:g}", broker_qty, guard.local_quantity, market_price if market_price > 0 else None, None, snapshot.endpoint_port)
    if not guard.allowed or guard.local_quantity != float(QUANTITY):
        return Close9432Plan(False, f"broker/local 9432 position guard blocked close: {guard.reason}", broker_qty, guard.local_quantity, market_price if market_price > 0 else None, None, snapshot.endpoint_port)
    if not _known_buy_is_trusted(accounting_records):
        return Close9432Plan(False, "known controlled 9432 BUY execution is not present in trusted accounting", broker_qty, guard.local_quantity, market_price if market_price > 0 else None, None, snapshot.endpoint_port)
    if market_price <= 0:
        return Close9432Plan(False, "broker 9432 market price is unavailable", broker_qty, guard.local_quantity, None, None, snapshot.endpoint_port)
    if not discovery.resolved or discovery.order_sent or len(discovery.candidates) != 1:
        return Close9432Plan(False, "9432 ContractDetails discovery is not uniquely resolved", broker_qty, guard.local_quantity, market_price, None, snapshot.endpoint_port)
    candidate = discovery.candidates[0]
    if not _candidate_is_exact(candidate):
        return Close9432Plan(False, "9432 broker contract/lot evidence is incomplete or changed", broker_qty, guard.local_quantity, market_price, None, snapshot.endpoint_port, candidate.liquid_hours, candidate.time_zone_id)
    if not liquid_session_is_open(candidate, now=now):
        return Close9432Plan(False, "9432 TSEJ liquid session is not currently open", broker_qty, guard.local_quantity, market_price, None, snapshot.endpoint_port, candidate.liquid_hours, candidate.time_zone_id)
    price = _limit_price(market_price, float(candidate.min_tick))
    return Close9432Plan(True, "controlled 9432 Paper position is eligible for an exact 100-share flatten-only close", broker_qty, guard.local_quantity, market_price, price, snapshot.endpoint_port, candidate.liquid_hours, candidate.time_zone_id)


def _open_order_exists(endpoint_port: int, *, wait_seconds: float = 2.0) -> bool:
    cfg = create_ibkr_paper_config(use_gateway=(int(endpoint_port) == 4002))
    broker = IbkrBrokerAdapter(cfg, enable_paper_order_transmission=False)
    try:
        if not broker.connect(connect_timeout=10.0):
            raise RuntimeError("cannot verify current 9432 open orders")
        client = broker._session.client
        client.reqOpenOrders()
        time.sleep(wait_seconds)
        return any(str(row.get("symbol", "")).strip().upper() == SYMBOL for row in client.open_orders.values())
    finally:
        broker.disconnect()


def _broker_flat_after_fill(*, attempts: int = 4, wait_seconds: float = 2.0) -> bool:
    for index in range(max(1, attempts)):
        snapshot = preview_ibkr_paper_account_snapshot()
        position = _stock_position(snapshot)
        quantity = 0.0 if position is None else float(position.quantity)
        if snapshot.ready and abs(quantity) <= 1e-9:
            return True
        if index + 1 < attempts:
            time.sleep(wait_seconds)
    return False


def _local_quantity(records: list[dict]) -> float | None:
    held = 0.0
    seen_exec_ids: set[str] = set()
    for row in records:
        if str(row.get("status", "")).strip().upper() != "FILLED" or str(row.get("ticker", "")).strip().upper() != SYMBOL:
            continue
        ids = [str(value or "").strip() for value in list(row.get("broker_exec_ids") or []) if str(value or "").strip()]
        if ids and any(value in seen_exec_ids for value in ids):
            continue
        try:
            qty = float(row.get("shares"))
        except (TypeError, ValueError):
            return None
        side = str(row.get("side", "")).strip().upper()
        if qty <= 0 or side not in {"BUY", "SELL"}:
            return None
        if side == "BUY":
            held += qty
        else:
            if qty > held + 1e-9:
                return None
            held -= qty
        seen_exec_ids.update(ids)
    return held


def _reconcile_until_local_flat(*, attempts: int = 4, wait_seconds: float = 2.0) -> tuple[bool, int, tuple[str, ...]]:
    total = 0
    errors: list[str] = []
    for index in range(max(1, attempts)):
        snapshot = preview_ibkr_paper_execution_snapshot()
        result = reconcile_execution_snapshot_to_ledger(snapshot, order_log_path=order_manager.ORDER_LOG_PATH)
        total += result.reconciled_count
        errors.extend(result.errors)
        records = list(order_manager.load_accounting_orders())
        if not result.errors and _local_quantity(records) == 0.0:
            return True, total, tuple(errors)
        if index + 1 < attempts:
            time.sleep(wait_seconds)
    return False, total, tuple(errors)


def run_9432_flat_close() -> Close9432Result:
    empty = Close9432Plan(False, "not evaluated", 0.0, None, None, None, None)
    if not SETTINGS.enable_paper_trading or not SETTINGS.enable_ibkr_paper:
        return Close9432Result(False, "IBKR Paper is not explicitly enabled", empty, None, False, False, 0, ())
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return Close9432Result(False, "Live Trading safety lock is not intact", empty, None, False, False, 0, ())
    if os.getenv("IBKR_9432_CLOSE_CONFIRM", "").strip() != CONFIRMATION_TEXT:
        return Close9432Result(False, "exact 9432 Paper close confirmation is missing", empty, None, False, False, 0, ())

    accounting_records = list(order_manager.load_accounting_orders())
    snapshot = preview_ibkr_paper_account_snapshot()
    discovery = discover_ibkr_paper_global_stock(symbol=SYMBOL, exchange=EXCHANGE, currency=CURRENCY)
    plan = build_9432_close_plan(snapshot, accounting_records=accounting_records, discovery=discovery)
    if not plan.ready or plan.limit_price is None or plan.endpoint_port is None:
        return Close9432Result(False, plan.reason, plan, None, False, False, 0, ())

    whatif = preview_9432_close_whatif(limit_price=plan.limit_price)
    if not whatif.ready:
        return Close9432Result(False, "9432 100-share SELL what-if did not pass", plan, None, False, False, 0, ())
    if _open_order_exists(plan.endpoint_port):
        return Close9432Result(False, "a 9432 open order already exists; close blocked", plan, None, False, False, 0, ())

    instrument = InstrumentSpec(
        symbol=SYMBOL,
        asset_class=AssetClass.STOCK,
        exchange=EXCHANGE,
        currency=CURRENCY,
        verified_paper_test_quantity=QUANTITY,
    )
    order = OrderRequest(
        symbol=SYMBOL,
        side=OrderSide.SELL,
        quantity=QUANTITY,
        order_type=OrderType.LIMIT,
        limit_price=plan.limit_price,
    )
    broker = _connect_first_available_paper_broker()
    service = ExecutionService(broker=broker, account=Account(initial_cash=0.0), risk_gate=build_shared_risk_gate())
    try:
        broker_result = service.execute_ibkr_paper_order(
            order,
            order_intent_id=CLOSE_INTENT_ID,
            instrument=instrument,
            apply_account_fill=False,
        )
    finally:
        broker.disconnect()

    confirmed = confirmed_fill_from_broker_result(broker_result, QUANTITY)
    if confirmed is None:
        return Close9432Result(True, "close order state is not a confirmed full fill; never resend automatically", plan, broker_result, False, False, 0, tuple(_broker_exec_ids(broker_result)))
    exec_ids = tuple(_broker_exec_ids(broker_result))
    if not exec_ids:
        return Close9432Result(True, "confirmed 9432 close fill lacks broker exec_id; never infer or resend", plan, broker_result, False, False, 0, ())
    broker_flat = _broker_flat_after_fill()
    if not broker_flat:
        return Close9432Result(True, "9432 close fill confirmed but broker-flat state is not yet proven; never resend", plan, broker_result, False, False, 0, exec_ids)
    local_flat, reconciled_count, reconcile_errors = _reconcile_until_local_flat()
    if reconcile_errors or not local_flat:
        reason = "broker is flat but durable local 9432 reconciliation is not proven; never resend"
        if reconcile_errors:
            reason += f": {list(reconcile_errors)}"
        return Close9432Result(True, reason, plan, broker_result, True, False, reconciled_count, exec_ids)
    return Close9432Result(True, "9432 Paper close completed: broker flat and durable local accounting reconciled flat", plan, broker_result, True, True, reconciled_count, exec_ids)


def main() -> int:
    result = run_9432_flat_close()
    broker_result = result.broker_result
    print("===== IBKR PAPER 9432/TSEJ 100-SHARE FLAT CLOSE =====")
    print("PLAN READY              :", result.plan.ready)
    print("PLAN REASON             :", result.plan.reason)
    print("BROKER 9432 QTY BEFORE  :", result.plan.broker_quantity)
    print("LOCAL 9432 QTY BEFORE   :", result.plan.local_quantity)
    print("BROKER MARKET PRICE     :", result.plan.market_price)
    print("AUTO LIMIT PRICE        :", result.plan.limit_price)
    print("TSEJ LIQUID HOURS       :", result.plan.liquid_hours)
    print("TSEJ TIME ZONE          :", result.plan.time_zone_id)
    print("CLOSE ATTEMPTED         :", result.attempted)
    print("CLOSE REASON            :", result.reason)
    print("BROKER SENT             :", getattr(broker_result, "sent", False))
    print("BROKER ORDER ID         :", getattr(broker_result, "order_id", None))
    print("BROKER STATUS           :", getattr(broker_result, "status", None))
    print("BROKER FILLED           :", getattr(broker_result, "filled_quantity", 0.0))
    print("BROKER AVG PRICE        :", getattr(broker_result, "avg_fill_price", None))
    print("CLOSE EXEC IDS          :", list(result.close_exec_ids))
    print("BROKER 9432 FLAT AFTER  :", result.broker_flat_after)
    print("LOCAL 9432 FLAT AFTER   :", result.local_flat_after)
    print("RECONCILED COUNT        :", result.reconciled_count)
    print("REAL LIVE ORDER SENT    : False")
    return 0 if result.broker_flat_after and result.local_flat_after else (1 if result.attempted else 2)


if __name__ == "__main__":
    raise SystemExit(main())
