"""Explicit read-only IBKR Live account preflight.

This module exists only to prove that a future real-cash pilot is pointed at the
intended Live account/session before any Live order transport is implemented.
It has no order API calls, never enables Live Trading, and requires an exact
operator confirmation before it will even open a Live socket connection.

Default IBKR endpoints are tried in this order:
- IB Gateway Live: 4001
- TWS Live: 7496

The raw account identifier is never written to the report. A SHA-256 fingerprint
is stored instead so later pilot steps can pin the same account without exposing
the identifier in ordinary logs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
from threading import Thread

from ai_asset_platform.brokers.ibkr_account_snapshot import (
    IbkrBrokerPosition,
    _AccountSnapshotProbe,
    _base_currency,
    _summary_value,
)
from ai_asset_platform.brokers.ibkr_thread_runner import (
    run_ibapi_message_loop_safely,
)


CONFIRMATION_ENV = "AI_ASSET_LIVE_READONLY_CONFIRM"
CONFIRMATION_VALUE = "READ_LIVE_ACCOUNT_ONLY"
DEFAULT_REPORT_PATH = Path("results/ibkr_live_readonly_account_latest.json")
LIVE_GATEWAY_PORT = 4001
LIVE_TWS_PORT = 7496
REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class IbkrLiveReadOnlyAccountSnapshot:
    attempted: bool
    connected: bool
    endpoint_port: int | None
    account_fingerprint: str | None
    account_ready: bool
    base_currency: str | None
    net_liquidation: float | None
    available_funds: float | None
    gross_position_value: float | None
    total_cash_value: float | None
    positions: tuple[IbkrBrokerPosition, ...] = ()
    blocked_reason: str | None = None
    order_sent: bool = False
    live_order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.attempted
            and self.connected
            and self.account_ready
            and self.account_fingerprint is not None
            and self.base_currency is not None
            and self.net_liquidation is not None
            and self.net_liquidation > 0
            and self.blocked_reason is None
            and not self.order_sent
            and not self.live_order_sent
        )


def _account_fingerprint(account_id: str) -> str:
    normalized = str(account_id).strip()
    if not normalized:
        raise ValueError("account_id is empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _blocked(reason: str) -> IbkrLiveReadOnlyAccountSnapshot:
    return IbkrLiveReadOnlyAccountSnapshot(
        attempted=False,
        connected=False,
        endpoint_port=None,
        account_fingerprint=None,
        account_ready=False,
        base_currency=None,
        net_liquidation=None,
        available_funds=None,
        gross_position_value=None,
        total_cash_value=None,
        positions=(),
        blocked_reason=reason,
        order_sent=False,
        live_order_sent=False,
        errors=(),
    )


def preview_ibkr_live_readonly_account_snapshot(
    *,
    timeout: float = 10.0,
    confirmation: str | None = None,
) -> IbkrLiveReadOnlyAccountSnapshot:
    """Read one complete Live account snapshot without any order API request."""
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
        probe = _AccountSnapshotProbe()
        client_id = 370 + index
        try:
            try:
                probe.connect("127.0.0.1", port, client_id)
            except OSError as exc:
                collected.append(f"{port}: {exc}")
                continue

            Thread(
                target=run_ibapi_message_loop_safely,
                kwargs={"client": probe, "errors": probe.errors},
                daemon=True,
            ).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                collected.extend(probe.errors)
                continue

            probe.reqManagedAccts()
            if not probe.accounts_ready.wait(timeout) or len(probe.accounts) != 1:
                collected.extend(probe.errors)
                collected.append(
                    f"{port}: expected exactly one managed Live account; got {len(probe.accounts)}"
                )
                continue
            account_id = probe.accounts[0]

            probe.reqAccountUpdates(True, account_id)
            probe.reqAccountSummary(
                1991,
                "All",
                "NetLiquidation,AvailableFunds,GrossPositionValue,TotalCashValue",
            )
            download_complete = probe.download_ready.wait(timeout)
            summary_complete = probe.summary_ready.wait(timeout)
            try:
                probe.cancelAccountSummary(1991)
            except Exception:
                pass
            probe.reqAccountUpdates(False, account_id)

            if not download_complete or not summary_complete or probe.fatal_error:
                collected.extend(probe.errors)
                if not download_complete:
                    collected.append(
                        f"{port}: Live account download did not complete before timeout"
                    )
                if not summary_complete:
                    collected.append(
                        f"{port}: Live account summary did not complete before timeout"
                    )
                continue

            base_currency = _base_currency(probe)
            return IbkrLiveReadOnlyAccountSnapshot(
                attempted=True,
                connected=True,
                endpoint_port=port,
                account_fingerprint=_account_fingerprint(account_id),
                account_ready=bool(probe.account_ready),
                base_currency=base_currency,
                net_liquidation=_summary_value(
                    probe, "NetLiquidation", base_currency
                ),
                available_funds=_summary_value(
                    probe, "AvailableFunds", base_currency
                ),
                gross_position_value=_summary_value(
                    probe, "GrossPositionValue", base_currency
                ),
                total_cash_value=_summary_value(
                    probe, "TotalCashValue", base_currency
                ),
                positions=tuple(probe.portfolio),
                blocked_reason=None,
                order_sent=False,
                live_order_sent=False,
                errors=tuple(collected + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrLiveReadOnlyAccountSnapshot(
        attempted=True,
        connected=False,
        endpoint_port=None,
        account_fingerprint=None,
        account_ready=False,
        base_currency=None,
        net_liquidation=None,
        available_funds=None,
        gross_position_value=None,
        total_cash_value=None,
        positions=(),
        blocked_reason="no Live endpoint produced a complete read-only snapshot",
        order_sent=False,
        live_order_sent=False,
        errors=tuple(collected),
    )


def persist_live_readonly_account_snapshot(
    snapshot: IbkrLiveReadOnlyAccountSnapshot,
    *,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        **asdict(snapshot),
        "ready": snapshot.ready,
        "raw_account_id_persisted": False,
        "connection_mode": "LIVE_READ_ONLY",
        "broker_connection_used": snapshot.attempted,
        "order_sent": False,
        "live_order_sent": False,
    }
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def main() -> int:
    snapshot = preview_ibkr_live_readonly_account_snapshot()
    persist_live_readonly_account_snapshot(snapshot)
    print("===== IBKR LIVE READ-ONLY ACCOUNT PREFLIGHT =====")
    print("ATTEMPTED          :", snapshot.attempted)
    print("CONNECTED          :", snapshot.connected)
    print("ENDPOINT PORT      :", snapshot.endpoint_port)
    print("READY              :", snapshot.ready)
    print("ACCOUNT READY      :", snapshot.account_ready)
    print("BASE CURRENCY      :", snapshot.base_currency)
    print("POSITION COUNT     :", len(snapshot.positions))
    print("RAW ACCOUNT ID     : NOT PERSISTED")
    print("BLOCKED REASON     :", snapshot.blocked_reason)
    print("ORDER SENT         : False")
    print("LIVE ORDER SENT    : False")
    print("REPORT             :", DEFAULT_REPORT_PATH)
    return 0 if snapshot.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
