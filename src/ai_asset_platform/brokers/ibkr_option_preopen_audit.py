"""Read-only pre-open gate for the pinned SPY option Paper E2E.

This module creates no Order and never calls placeOrder/cancelOrder. It checks
Paper/Live safety settings, exact contract identity, current flat position,
open orders across API clients, execution-snapshot availability, and whether a
previous exact closed round-trip can already be recovered and audited.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.accounting.options_postfill_audit import (
    evaluate_option_postfill_from_existing_snapshot,
)
from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_execution_snapshot import preview_ibkr_paper_execution_snapshot
from ai_asset_platform.brokers.ibkr_option_paper_roundtrip import (
    CON_ID,
    EXPIRY,
    LOCAL_SYMBOL,
    MULTIPLIER,
    RIGHT,
    STRIKE,
    _verified_target,
)
from ai_asset_platform.brokers.ibkr_option_position_probe import probe_option_position
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely
from ai_asset_platform.core.settings import SETTINGS


@dataclass(frozen=True)
class OptionPreopenAuditResult:
    ready: bool
    reason: str
    endpoint_port: int | None
    exact_target_resolved: bool
    position_quantity: float | None
    position_flat: bool
    all_open_orders_ready: bool
    matching_open_order_count: int
    execution_snapshot_ready: bool
    exact_execution_count: int
    prior_roundtrip_recovered: bool
    prior_roundtrip_realized_pnl_usd: str | None
    errors: tuple[str, ...] = field(default_factory=tuple)
    real_order_sent: bool = False
    live_order_sent: bool = False
    exact_execution_details: tuple[str, ...] = field(default_factory=tuple)


class _AllOpenOrdersProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready = Event()
        self.open_ready = Event()
        self.open_orders: list[tuple[str, str, int]] = []
        self.errors: list[str] = []
        self.fatal = False

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.ready.set()

    def openOrder(self, orderId, contract, order, orderState) -> None:  # noqa: N802
        self.open_orders.append(
            (
                str(getattr(contract, "localSymbol", "") or "").upper(),
                str(getattr(contract, "secType", "") or "").upper(),
                int(orderId),
            )
        )

    def openOrderEnd(self) -> None:  # noqa: N802
        self.open_ready.set()

    def error(self, reqId, *args) -> None:
        if len(args) >= 3:
            code, text = args[-2], args[-1]
        elif len(args) >= 2:
            code, text = args[0], args[1]
        else:
            return
        self.errors.append(f"{code}: {text}")
        try:
            code_i = int(code)
        except (TypeError, ValueError):
            return
        if code_i in {326, 502, 503, 504, 1100}:
            self.fatal = True
            self.ready.set()
            self.open_ready.set()


def _all_open_orders(*, timeout: float = 15.0) -> tuple[bool, int | None, int, tuple[str, ...]]:
    cfg = create_ibkr_paper_config(use_gateway=True)
    probe = _AllOpenOrdersProbe()
    try:
        try:
            probe.connect(cfg.host, cfg.port, cfg.client_id + 298)
        except OSError as exc:
            return False, cfg.port, 0, (str(exc),)
        Thread(
            target=run_ibapi_message_loop_safely,
            kwargs={"client": probe, "errors": probe.errors},
            daemon=True,
        ).start()
        if not probe.ready.wait(timeout) or probe.fatal:
            return False, cfg.port, 0, tuple(probe.errors)
        probe.reqAllOpenOrders()
        if not probe.open_ready.wait(timeout) or probe.fatal:
            return False, cfg.port, 0, tuple(probe.errors)
        matching = sum(
            1
            for local, sec_type, _ in probe.open_orders
            if local == LOCAL_SYMBOL.upper() and sec_type == "OPT"
        )
        return True, cfg.port, matching, tuple(probe.errors)
    finally:
        if probe.isConnected():
            probe.disconnect()


def _exact_execution_rows(snapshot):
    return [
        row
        for row in snapshot.executions
        if row.sec_type == "OPT"
        and (row.local_symbol or "").upper() == LOCAL_SYMBOL.upper()
        and row.con_id == CON_ID
        and (row.expiry or "") == EXPIRY
        and (row.multiplier or "") == MULTIPLIER
        and bool(row.exec_id)
    ]


def _exact_execution_count(snapshot) -> int:
    return len(_exact_execution_rows(snapshot))


def _exact_execution_details(snapshot) -> tuple[str, ...]:
    rows = _exact_execution_rows(snapshot)
    return tuple(
        f"side={row.side} qty={row.quantity:g} price={row.price:g} "
        f"order_id={row.order_id} exec_id={row.exec_id} time={row.time or 'UNKNOWN'}"
        for row in sorted(rows, key=lambda item: (str(item.time), int(item.order_id), str(item.exec_id)))
    )


def run_option_preopen_audit(*, timeout: float = 15.0) -> OptionPreopenAuditResult:
    if not SETTINGS.enable_ibkr_paper:
        return OptionPreopenAuditResult(False, "IBKR Paper is not explicitly enabled", None, False, None, False, False, 0, False, 0, False, None)
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return OptionPreopenAuditResult(False, "Live Trading safety lock is not intact", None, False, None, False, False, 0, False, 0, False, None)

    errors: list[str] = []
    endpoint_port, candidate, discovery_errors = _verified_target()
    errors.extend(discovery_errors)
    exact_target = bool(
        candidate is not None
        and candidate.con_id == CON_ID
        and candidate.local_symbol == LOCAL_SYMBOL
        and candidate.expiry == EXPIRY
        and candidate.strike == STRIKE
        and str(candidate.right).upper() == RIGHT
        and str(candidate.multiplier) == MULTIPLIER
    )

    position = probe_option_position(timeout=timeout)
    errors.extend(position.errors)
    open_ready, open_port, matching_open, open_errors = _all_open_orders(timeout=timeout)
    errors.extend(open_errors)
    snapshot = preview_ibkr_paper_execution_snapshot(timeout=timeout)
    errors.extend(snapshot.errors)
    exact_exec_count = _exact_execution_count(snapshot) if snapshot.ready else 0
    exact_exec_details = _exact_execution_details(snapshot) if snapshot.ready else ()

    broker_flat = bool(position.connected and position.quantity is not None and position.flat)
    prior = evaluate_option_postfill_from_existing_snapshot(snapshot, broker_flat=broker_flat)
    prior_recovered = prior.ready
    prior_pnl = str(prior.realized_pnl_usd) if prior.realized_pnl_usd is not None else None

    core_ready = bool(
        exact_target
        and position.connected
        and position.quantity is not None
        and position.flat
        and open_ready
        and matching_open == 0
        and snapshot.ready
    )
    if not exact_target:
        reason = "exact pinned SPY option contract did not resolve"
    elif not position.connected or position.quantity is None:
        reason = "option position snapshot is not ready"
    elif not position.flat:
        reason = f"option position is not flat: {position.quantity}"
    elif not open_ready:
        reason = "all-open-orders snapshot is not ready"
    elif matching_open:
        reason = f"matching SPY option open orders exist: {matching_open}"
    elif not snapshot.ready:
        reason = "execution snapshot is not ready"
    elif prior_recovered:
        reason = "pre-open gate passed and a prior complete SPY option Paper round-trip is already recoverable"
    else:
        reason = "pre-open gate passed; no prior complete round-trip proof, ready for one controlled Paper E2E during RTH"

    return OptionPreopenAuditResult(
        core_ready,
        reason,
        endpoint_port or open_port or position.endpoint_port,
        exact_target,
        position.quantity,
        position.flat,
        open_ready,
        matching_open,
        snapshot.ready,
        exact_exec_count,
        prior_recovered,
        prior_pnl,
        tuple(errors),
        False,
        False,
        exact_exec_details,
    )


def main() -> int:
    result = run_option_preopen_audit()
    print("===== IBKR PAPER SPY OPTION PRE-OPEN AUDIT =====")
    print("READY                       :", result.ready)
    print("REASON                      :", result.reason)
    print("ENDPOINT PORT               :", result.endpoint_port)
    print("PINNED TARGET RESOLVED      :", result.exact_target_resolved)
    print("PINNED LOCAL SYMBOL         :", LOCAL_SYMBOL)
    print("PINNED CON ID               :", CON_ID)
    print("PINNED EXPIRY/STRIKE/RIGHT  :", f"{EXPIRY} / {STRIKE} / {RIGHT}")
    print("PINNED MULTIPLIER           :", MULTIPLIER)
    print("POSITION QUANTITY           :", result.position_quantity)
    print("POSITION FLAT               :", result.position_flat)
    print("ALL OPEN ORDERS READY       :", result.all_open_orders_ready)
    print("MATCHING OPEN ORDER COUNT   :", result.matching_open_order_count)
    print("EXECUTION SNAPSHOT READY    :", result.execution_snapshot_ready)
    print("EXACT HISTORICAL EXECUTIONS :", result.exact_execution_count)
    for index, detail in enumerate(result.exact_execution_details, start=1):
        print(f"EXACT EXECUTION {index:<12}:", detail)
    print("PRIOR ROUNDTRIP RECOVERED   :", result.prior_roundtrip_recovered)
    print("PRIOR REALIZED PNL USD      :", result.prior_roundtrip_realized_pnl_usd)
    print("ERRORS                      :", list(result.errors))
    print("REAL ORDER SENT             :", result.real_order_sent)
    print("LIVE ORDER SENT             :", result.live_order_sent)
    return 0 if result.ready and not result.real_order_sent and not result.live_order_sent else 2


if __name__ == "__main__":
    raise SystemExit(main())
