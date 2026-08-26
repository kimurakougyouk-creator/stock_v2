"""Read-only snapshot of every open IBKR Paper order across API clients.

The probe calls ``reqAllOpenOrders`` only.  It never places, changes, cancels,
or retries an order.  Any returned order is evidence for manual review; this
module deliberately takes no corrective broker action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_thread_runner import (
    run_ibapi_message_loop_safely,
)


@dataclass(frozen=True)
class IbkrOpenOrderEvidence:
    order_id: int
    symbol: str
    local_symbol: str
    sec_type: str
    currency: str
    exchange: str
    action: str
    quantity: float
    order_type: str
    status: str
    client_id: int | None
    perm_id: int | None


@dataclass(frozen=True)
class IbkrAllOpenOrdersSnapshot:
    connected: bool
    ready: bool
    endpoint_port: int | None
    orders: tuple[IbkrOpenOrderEvidence, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)
    order_sent: bool = False


def _finite_float(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return 0.0
    return parsed


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _AllOpenOrdersProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.orders_ready = Event()
        self.orders: list[IbkrOpenOrderEvidence] = []
        self.errors: list[str] = []
        self.fatal = False

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def openOrder(self, orderId, contract, order, orderState) -> None:  # noqa: N802
        self.orders.append(
            IbkrOpenOrderEvidence(
                order_id=int(orderId),
                symbol=str(getattr(contract, "symbol", "") or "").strip().upper(),
                local_symbol=str(
                    getattr(contract, "localSymbol", "") or ""
                ).strip().upper(),
                sec_type=str(getattr(contract, "secType", "") or "").strip().upper(),
                currency=str(getattr(contract, "currency", "") or "").strip().upper(),
                exchange=str(getattr(contract, "exchange", "") or "").strip().upper(),
                action=str(getattr(order, "action", "") or "").strip().upper(),
                quantity=_finite_float(getattr(order, "totalQuantity", 0)),
                order_type=str(getattr(order, "orderType", "") or "").strip().upper(),
                status=str(getattr(orderState, "status", "") or "").strip(),
                client_id=_optional_int(getattr(order, "clientId", None)),
                perm_id=_optional_int(getattr(order, "permId", None)),
            )
        )

    def openOrderEnd(self) -> None:  # noqa: N802
        self.orders_ready.set()

    def error(self, reqId, *args) -> None:
        if len(args) >= 3:
            code, message = args[-2], args[-1]
        elif len(args) >= 2:
            code, message = args[0], args[1]
        else:
            return
        self.errors.append(f"{code}: {message}")
        try:
            parsed_code = int(code)
        except (TypeError, ValueError):
            return
        if parsed_code in {326, 502, 503, 504, 1100}:
            self.fatal = True
            self.connected_ready.set()
            self.orders_ready.set()


def preview_ibkr_paper_all_open_orders(
    *, timeout: float = 10.0
) -> IbkrAllOpenOrdersSnapshot:
    """Collect all currently open Paper orders without taking broker action."""
    collected_errors: list[str] = []
    for use_gateway in (True, False):
        config = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _AllOpenOrdersProbe()
        try:
            try:
                probe.connect(config.host, config.port, config.client_id + 330)
            except OSError as exc:
                collected_errors.append(f"{config.port}: {exc}")
                continue
            Thread(
                target=run_ibapi_message_loop_safely,
                kwargs={"client": probe, "errors": probe.errors},
                daemon=True,
            ).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal:
                collected_errors.extend(probe.errors)
                continue
            probe.reqAllOpenOrders()
            if not probe.orders_ready.wait(timeout) or probe.fatal:
                collected_errors.extend(probe.errors)
                continue
            return IbkrAllOpenOrdersSnapshot(
                connected=True,
                ready=True,
                endpoint_port=config.port,
                orders=tuple(probe.orders),
                errors=tuple(probe.errors),
                order_sent=False,
            )
        finally:
            if probe.isConnected():
                probe.disconnect()
    return IbkrAllOpenOrdersSnapshot(
        connected=False,
        ready=False,
        endpoint_port=None,
        orders=(),
        errors=tuple(collected_errors),
        order_sent=False,
    )


def main() -> int:
    result = preview_ibkr_paper_all_open_orders()
    print("===== IBKR PAPER ALL OPEN ORDERS SNAPSHOT =====")
    print("MODE          : READ ONLY")
    print("READY         :", result.ready)
    print("ENDPOINT PORT :", result.endpoint_port)
    print("OPEN COUNT    :", len(result.orders))
    for index, order in enumerate(result.orders, start=1):
        print(
            f"OPEN {index}: order_id={order.order_id} symbol={order.symbol} "
            f"local_symbol={order.local_symbol} sec_type={order.sec_type} "
            f"side={order.action} qty={order.quantity:g} type={order.order_type} "
            f"status={order.status or 'UNKNOWN'} client_id={order.client_id} "
            f"perm_id={order.perm_id}"
        )
    print("ERRORS        :", list(result.errors))
    print("ORDER SENT    :", result.order_sent)
    print("CANCEL SENT   : False")
    print("LIVE ORDER SENT: False")
    return 0 if result.ready and not result.order_sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
