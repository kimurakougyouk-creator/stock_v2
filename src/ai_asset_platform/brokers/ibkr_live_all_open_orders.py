"""Explicit read-only snapshot of all open IBKR Live orders.

This is a preparation/preflight component only. It identifies the managed Live
account from the same socket used for ``reqAllOpenOrders`` and persists only its
SHA-256 fingerprint. It never places, modifies, cancels, retries, closes, or
previews an order.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Event, Thread

from ai_asset_platform.brokers.ibkr_all_open_orders_snapshot import (
    IbkrOpenOrderEvidence,
    _AllOpenOrdersProbe,
)
from ai_asset_platform.brokers.ibkr_live_readonly_account import (
    CONFIRMATION_ENV,
    CONFIRMATION_VALUE,
    LIVE_GATEWAY_PORT,
    LIVE_TWS_PORT,
    _account_fingerprint,
)
from ai_asset_platform.brokers.ibkr_thread_runner import (
    run_ibapi_message_loop_safely,
)


DEFAULT_REPORT_PATH = Path("results/ibkr_live_all_open_orders_latest.json")
REPORT_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class IbkrLiveAllOpenOrdersSnapshot:
    attempted: bool
    connected: bool
    ready: bool
    endpoint_port: int | None
    account_fingerprint: str | None = None
    orders: tuple[IbkrOpenOrderEvidence, ...] = ()
    blocked_reason: str | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    order_sent: bool = False
    cancel_sent: bool = False
    live_order_sent: bool = False


class _LiveAllOpenOrdersProbe(_AllOpenOrdersProbe):
    """Read-only probe that also binds evidence to the same managed account."""

    def __init__(self) -> None:
        super().__init__()
        self.accounts_ready = Event()
        self.accounts: list[str] = []

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [
            item.strip() for item in str(accountsList or "").split(",") if item.strip()
        ]
        self.accounts_ready.set()


def _blocked(reason: str) -> IbkrLiveAllOpenOrdersSnapshot:
    return IbkrLiveAllOpenOrdersSnapshot(
        attempted=False,
        connected=False,
        ready=False,
        endpoint_port=None,
        account_fingerprint=None,
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
        probe = _LiveAllOpenOrdersProbe()
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
            # Do not rely on an unsolicited managedAccounts callback. Request the
            # managed account explicitly from this exact socket before any open-
            # order evidence is accepted, so the fingerprint and order snapshot
            # are provably session-bound.
            probe.reqManagedAccts()
            if not probe.accounts_ready.wait(timeout) or probe.fatal:
                collected.extend(probe.errors)
                collected.append(f"{port}: managed account identity was not received")
                continue
            if len(probe.accounts) != 1:
                collected.append(
                    f"{port}: expected exactly one managed Live account; found {len(probe.accounts)}"
                )
                continue
            account_fingerprint = _account_fingerprint(probe.accounts[0])
            probe.reqAllOpenOrders()
            if not probe.orders_ready.wait(timeout) or probe.fatal:
                collected.extend(probe.errors)
                continue
            return IbkrLiveAllOpenOrdersSnapshot(
                attempted=True,
                connected=True,
                ready=True,
                endpoint_port=port,
                account_fingerprint=account_fingerprint,
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
        account_fingerprint=None,
        orders=(),
        blocked_reason="no Live endpoint produced a complete account-bound open-order snapshot",
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
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "attempted": snapshot.attempted,
        "connected": snapshot.connected,
        "ready": snapshot.ready,
        "endpoint_port": snapshot.endpoint_port,
        "account_fingerprint": snapshot.account_fingerprint,
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
    print("ACCOUNT FP      :", snapshot.account_fingerprint)
    print("OPEN ORDER COUNT:", len(snapshot.orders))
    print("BLOCKED REASON  :", snapshot.blocked_reason)
    print("ORDER SENT      : False")
    print("CANCEL SENT     : False")
    print("LIVE ORDER SENT : False")
    print("REPORT          :", DEFAULT_REPORT_PATH)
    return 0 if snapshot.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
