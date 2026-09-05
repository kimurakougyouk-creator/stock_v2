"""Explicit read-only snapshot of all open IBKR Live orders.

This is a preparation/preflight component only. It calls ``reqAllOpenOrders``
against the Live TWS/Gateway endpoints after the same exact read-only
confirmation used by the Live account preflight. It never places, modifies,
cancels, retries, closes, or previews an order.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from threading import Thread

from ai_asset_platform.brokers.ibkr_all_open_orders_snapshot import (
    IbkrOpenOrderEvidence,
    _AllOpenOrdersProbe,
)
from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    CONFIRMATION_ENV,
    CONFIRMATION_VALUE,
    LIVE_GATEWAY_PORT,
    LIVE_TWS_PORT,
)
from ai_asset_platform.brokers.ibkr_thread_runner import (
    run_ibapi_message_loop_safely,
)


DEFAULT_REPORT_PATH = Path("results/ibkr_live_all_open_orders_latest.json")
REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IbkrLiveAllOpenOrdersSnapshot:
    attempted: bool
    connected: bool
    ready: bool
    endpoint_port: int | None
    orders: tuple[IbkrOpenOrderEvidence, ...] = ()
    blocked_reason: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    order_sent: bool = False
    cancel_sent: bool = False
    live_order_sent: bool = False


def _blocked(reason: str) -> IbkrLiveAllOpenOrdersSnapshot:
    return IbkrLiveAllOpenOrdersSnapshot(
        attempted=False,
        connected=False,
        ready=False,
        endpoint_port=None,
        orders=(),
        blocked_reason=reason,
        errors=(),
        order_sent=False,
        cancel_sent=False,
        live_order_sent=False,
    )


def preview_ibkr_live_all_open_orders(
    *, timeout: float = 10.0, confirmation: str | None = None,
) -> IbkrLiveAllOpenOrdersSnapshot:
    """Collect all currently open Live orders without taking broker action."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    supplied = (
        str(confirmation).strip()
        if confirmation is not None
        else os.getenv(CONFIRMATION_ENV, "").strip()
    )
    if supplied != CONFIRMATION_VALUE:
        return _blocked("exact Live read-only confirmation is missing")

    collected: list[str] = []
    for index, port in enumerate((LIVE_GATEWAY_PORT, LIVE_TWS_PORT), start=1):
        probe = _AllOpenOrdersProbe()
        try:
            try:
                probe.connect("127.0.0.1", port, 470 + index)
            except OSError as exc:
                collected.append(f"{port}: {exc}")
                continue
            Thread(
                target=run_ibapi_message_loop_safely,
                kwargs={"client": probe, "errors": probe.errors},
                daemon=True,
            ).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal:
                collected.extend(probe.errors)
                continue
            probe.reqAllOpenOrders()
            if not probe.orders_ready.wait(timeout) or probe.fatal:
                collected.extend(probe.errors)
                continue
            return IbkrLiveAllOpenOrdersSnapshot(
                attempted=True,
                connected=True,
                ready=True,
                endpoint_port=port,
                orders=tuple(probe.orders),
                blocked_reason=None,
                errors=tuple(collected + probe.errors),
                order_sent=False,
                cancel_sent=False,
                live_order_sent=False,
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrLiveAllOpenOrdersSnapshot(
        attempted=True,
        connected=False,
        ready=False,
        endpoint_port=None,
        orders=(),
        blocked_reason="no Live endpoint produced a complete open-order snapshot",
        errors=tuple(collected),
        order_sent=False,
        cancel_sent=False,
        live_order_sent=False,
    )


def persist_live_all_open_orders(
    snapshot: IbkrLiveAllOpenOrdersSnapshot,
    *, report_path: Path = DEFAULT_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "attempted": snapshot.attempted,
        "connected": snapshot.connected,
        "ready": snapshot.ready,
        "endpoint_port": snapshot.endpoint_port,
        "open_order_count": len(snapshot.orders),
        "orders": [asdict(order) for order in snapshot.orders],
        "blocked_reason": snapshot.blocked_reason,
        "errors": list(snapshot.errors),
        "connection_mode": "LIVE_READ_ONLY",
        "broker_connection_used": snapshot.attempted,
        "order_sent": False,
        "cancel_sent": False,
        "live_order_sent": False,
    }
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def main() -> int:
    snapshot = preview_ibkr_live_all_open_orders()
    persist_live_all_open_orders(snapshot)
    print("===== IBKR LIVE ALL OPEN ORDERS — READ ONLY =====")
    print("ATTEMPTED       :", snapshot.attempted)
    print("CONNECTED       :", snapshot.connected)
    print("READY           :", snapshot.ready)
    print("ENDPOINT PORT   :", snapshot.endpoint_port)
    print("OPEN ORDER COUNT:", len(snapshot.orders))
    print("BLOCKED REASON  :", snapshot.blocked_reason)
    print("ORDER SENT      : False")
    print("CANCEL SENT     : False")
    print("LIVE ORDER SENT : False")
    print("REPORT          :", DEFAULT_REPORT_PATH)
    return 0 if snapshot.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
