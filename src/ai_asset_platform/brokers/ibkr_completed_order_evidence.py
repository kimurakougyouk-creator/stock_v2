"""Read-only IBKR Paper completed-order evidence for AAPL reconciliation.

This module requests completed orders and the current Paper account snapshot.
It never creates, modifies, cancels, or transmits an order and never mutates the
local durable ledger. Missing broker history remains unknown rather than being
inferred from position cost or local legacy rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrPaperAccountSnapshot,
    preview_ibkr_paper_account_snapshot,
)
from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config


@dataclass(frozen=True)
class IbkrCompletedOrderEvidence:
    order_id: int
    perm_id: int
    symbol: str
    sec_type: str
    currency: str
    exchange: str
    action: str
    quantity: float
    order_type: str
    limit_price: float | None
    status: str
    completed_time: str
    completed_status: str
    account: str
    order_ref: str


@dataclass(frozen=True)
class IbkrPaperCompletedOrderSnapshot:
    connected: bool
    endpoint_port: int | None
    orders: tuple[IbkrCompletedOrderEvidence, ...] = ()
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.connected and not self.order_sent


@dataclass(frozen=True)
class AaplCompletedOrderAudit:
    account_ready: bool
    completed_orders_ready: bool
    endpoint_port: int | None
    broker_quantity: float
    broker_average_cost: float | None
    aapl_completed_orders: tuple[IbkrCompletedOrderEvidence, ...]
    aapl_completed_buy_quantity: float
    next_action: str
    order_sent: bool = False
    ledger_changed: bool = False


def _parse_error(args: tuple[object, ...]) -> tuple[int, str] | None:
    if len(args) >= 4:
        code, text = args[1], args[2]
    elif len(args) >= 2:
        code, text = args[0], args[1]
    else:
        return None
    try:
        return int(code), str(text)
    except (TypeError, ValueError):
        return None


def _positive_or_none(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class _CompletedOrderProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.orders_ready = Event()
        self.orders: list[IbkrCompletedOrderEvidence] = []
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def completedOrder(self, contract, order, orderState) -> None:  # noqa: N802
        try:
            quantity = float(getattr(order, "totalQuantity", 0.0) or 0.0)
            order_id = int(getattr(order, "orderId", 0) or 0)
            perm_id = int(getattr(order, "permId", 0) or 0)
        except (TypeError, ValueError):
            return
        if quantity <= 0:
            return
        raw_action = str(getattr(order, "action", "") or "").strip().upper()
        action = {"BOT": "BUY", "SLD": "SELL"}.get(raw_action, raw_action)
        self.orders.append(
            IbkrCompletedOrderEvidence(
                order_id=order_id,
                perm_id=perm_id,
                symbol=str(getattr(contract, "symbol", "") or "").strip().upper(),
                sec_type=str(getattr(contract, "secType", "") or "").strip().upper(),
                currency=str(getattr(contract, "currency", "") or "").strip().upper(),
                exchange=str(
                    getattr(contract, "primaryExchange", "")
                    or getattr(contract, "exchange", "")
                    or ""
                ).strip().upper(),
                action=action,
                quantity=quantity,
                order_type=str(getattr(order, "orderType", "") or "").strip().upper(),
                limit_price=_positive_or_none(getattr(order, "lmtPrice", None)),
                status=str(getattr(orderState, "status", "") or "").strip(),
                completed_time=str(getattr(orderState, "completedTime", "") or "").strip(),
                completed_status=str(getattr(orderState, "completedStatus", "") or "").strip(),
                account=str(getattr(order, "account", "") or "").strip(),
                order_ref=str(getattr(order, "orderRef", "") or "").strip(),
            )
        )

    def completedOrdersEnd(self) -> None:  # noqa: N802
        self.orders_ready.set()

    def error(self, reqId, *args):
        parsed = _parse_error(args)
        if parsed is None:
            return
        code, text = parsed
        message = f"{code}: {text}"
        self.errors.append(message)
        if code in {326, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.orders_ready.set()


def preview_ibkr_paper_completed_orders(*, timeout: float = 10.0) -> IbkrPaperCompletedOrderSnapshot:
    """Request broker-reported completed orders, auto-detecting 4002 then 7497."""
    collected: list[str] = []
    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _CompletedOrderProbe()
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 273)
            except OSError as exc:
                collected.append(f"{cfg.port}: {exc}")
                continue
            Thread(target=probe.run, daemon=True).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                collected.extend(probe.errors)
                continue
            probe.reqCompletedOrders(False)
            if not probe.orders_ready.wait(timeout) or probe.fatal_error:
                collected.extend(probe.errors)
                continue
            deduped: dict[tuple[int, int, str, str, float], IbkrCompletedOrderEvidence] = {}
            for item in probe.orders:
                key = (item.order_id, item.perm_id, item.symbol, item.action, item.quantity)
                deduped.setdefault(key, item)
            return IbkrPaperCompletedOrderSnapshot(
                connected=True,
                endpoint_port=cfg.port,
                orders=tuple(deduped.values()),
                order_sent=False,
                errors=tuple(collected + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()
    return IbkrPaperCompletedOrderSnapshot(
        connected=False,
        endpoint_port=None,
        orders=(),
        order_sent=False,
        errors=tuple(collected),
    )


def _aapl_position(account: IbkrPaperAccountSnapshot):
    matches = [
        item for item in account.positions
        if str(item.symbol).strip().upper() == "AAPL" and item.sec_type in {"STK", "ETF"}
    ]
    return matches[0] if len(matches) == 1 else None


def _aapl_next_action(*, broker_quantity: float, completed_buy_quantity: float, completed_count: int) -> str:
    if broker_quantity == 0:
        return "AAPL_BROKER_POSITION_IS_FLAT"
    if completed_count == 0:
        return "AAPL_COMPLETED_ORDER_HISTORY_UNAVAILABLE_KEEP_BLOCKED"
    if completed_buy_quantity >= broker_quantity > 0:
        return "REVIEW_AAPL_COMPLETED_ORDER_EVIDENCE_FOR_RECOVERY"
    return "AAPL_COMPLETED_ORDER_EVIDENCE_INCOMPLETE_KEEP_BLOCKED"


def audit_aapl_completed_order_evidence(
    *,
    account: IbkrPaperAccountSnapshot | None = None,
    completed_snapshot: IbkrPaperCompletedOrderSnapshot | None = None,
) -> AaplCompletedOrderAudit:
    broker_account = account or preview_ibkr_paper_account_snapshot()
    completed = completed_snapshot or preview_ibkr_paper_completed_orders()
    position = _aapl_position(broker_account)
    broker_quantity = 0.0 if position is None else float(position.quantity)
    broker_average_cost = (
        None if position is None or float(position.average_cost) <= 0
        else float(position.average_cost)
    )
    aapl_orders = tuple(
        item for item in completed.orders
        if item.symbol == "AAPL" and item.sec_type in {"STK", "ETF"}
    )
    aapl_buys = tuple(item for item in aapl_orders if item.action == "BUY")
    completed_buy_quantity = sum(float(item.quantity) for item in aapl_buys)
    if not broker_account.ready:
        next_action = "BLOCKED_BROKER_ACCOUNT_SNAPSHOT_NOT_READY"
    elif not completed.ready:
        next_action = "BLOCKED_COMPLETED_ORDER_SNAPSHOT_NOT_READY"
    else:
        next_action = _aapl_next_action(
            broker_quantity=broker_quantity,
            completed_buy_quantity=completed_buy_quantity,
            completed_count=len(aapl_orders),
        )
    return AaplCompletedOrderAudit(
        account_ready=broker_account.ready,
        completed_orders_ready=completed.ready,
        endpoint_port=broker_account.endpoint_port or completed.endpoint_port,
        broker_quantity=broker_quantity,
        broker_average_cost=broker_average_cost,
        aapl_completed_orders=aapl_orders,
        aapl_completed_buy_quantity=completed_buy_quantity,
        next_action=next_action,
        order_sent=bool(broker_account.order_sent or completed.order_sent),
        ledger_changed=False,
    )


def main() -> int:
    result = audit_aapl_completed_order_evidence()
    print("===== IBKR PAPER AAPL COMPLETED-ORDER EVIDENCE =====")
    print("ACCOUNT READY           :", result.account_ready)
    print("COMPLETED ORDERS READY  :", result.completed_orders_ready)
    print("ENDPOINT PORT           :", result.endpoint_port)
    print("BROKER AAPL QTY         :", result.broker_quantity)
    print("BROKER AAPL AVG COST    :", result.broker_average_cost)
    print("AAPL COMPLETED COUNT    :", len(result.aapl_completed_orders))
    print("AAPL COMPLETED BUY QTY  :", result.aapl_completed_buy_quantity)
    print("LEDGER CHANGED          :", result.ledger_changed)
    print("ORDER SENT              :", result.order_sent)
    print("NEXT ACTION             :", result.next_action)
    for index, item in enumerate(result.aapl_completed_orders, start=1):
        print(
            f"AAPL ORDER {index}: action={item.action} qty={item.quantity:g} "
            f"currency={item.currency or 'UNKNOWN'} order_id={item.order_id} "
            f"perm_id={item.perm_id} type={item.order_type or 'UNKNOWN'} "
            f"limit={item.limit_price} status={item.status or 'UNKNOWN'} "
            f"completed_status={item.completed_status or 'UNKNOWN'} "
            f"completed_time={item.completed_time or 'UNKNOWN'} "
            f"order_ref={item.order_ref or 'NONE'}"
        )
    print("REAL LIVE ORDER SENT    : False")
    return 0 if result.account_ready and result.completed_orders_ready and not result.order_sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
