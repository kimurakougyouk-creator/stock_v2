"""Read-only IBKR Paper FX snapshot for explicit accounting conversion.

This module requests only market data for an explicit CASH/IDEALPRO pair. It
never creates or transmits an Order. A usable conversion rate requires both a
positive bid and ask from the same snapshot; otherwise the result fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_fx_discovery import build_fx_discovery_contract


@dataclass(frozen=True)
class IbkrFxSnapshotResult:
    connected: bool
    endpoint_port: int | None
    base_currency: str
    quote_currency: str
    exchange: str
    bid: float | None
    ask: float | None
    rate: float | None
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return (
            self.connected
            and self.rate is not None
            and self.rate > 0
            and not self.order_sent
        )


class _FxSnapshotProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.snapshot_ready = Event()
        self.bid: float | None = None
        self.ask: float | None = None
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def tickPrice(self, reqId, tickType, price, attrib):  # noqa: N802
        try:
            value = float(price)
        except (TypeError, ValueError):
            return
        if value <= 0:
            return
        if int(tickType) == 1:  # bid
            self.bid = value
        elif int(tickType) == 2:  # ask
            self.ask = value

    def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802
        self.snapshot_ready.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
        message = f"{errorCode}: {errorString}"
        self.errors.append(message)
        if int(errorCode) in {200, 326, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.snapshot_ready.set()


def _midpoint(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (float(bid) + float(ask)) / 2.0


def preview_ibkr_paper_fx_rate(
    *,
    base_currency: str,
    quote_currency: str,
    exchange: str = "IDEALPRO",
    timeout: float = 10.0,
) -> IbkrFxSnapshotResult:
    """Request one read-only FX bid/ask snapshot from Paper TWS/Gateway.

    The returned rate is quote-currency units per one base-currency unit, using
    the midpoint of positive bid/ask values from the broker snapshot.
    """
    contract: Contract = build_fx_discovery_contract(
        base_currency=base_currency,
        quote_currency=quote_currency,
        exchange=exchange,
    )
    connection_errors: list[str] = []

    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _FxSnapshotProbe()
        try:
            probe.connect(cfg.host, cfg.port, cfg.client_id + 260)
            Thread(target=probe.run, daemon=True).start()
            ready = probe.connected_ready.wait(timeout)
            if not ready or probe.fatal_error:
                connection_errors.extend(probe.errors)
                continue

            probe.reqMktData(1, contract, "", True, False, [])
            probe.snapshot_ready.wait(timeout)
            rate = _midpoint(probe.bid, probe.ask)
            return IbkrFxSnapshotResult(
                connected=True,
                endpoint_port=cfg.port,
                base_currency=contract.symbol,
                quote_currency=contract.currency,
                exchange=contract.exchange,
                bid=probe.bid,
                ask=probe.ask,
                rate=rate,
                order_sent=False,
                errors=tuple(connection_errors + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrFxSnapshotResult(
        connected=False,
        endpoint_port=None,
        base_currency=contract.symbol,
        quote_currency=contract.currency,
        exchange=contract.exchange,
        bid=None,
        ask=None,
        rate=None,
        order_sent=False,
        errors=tuple(connection_errors),
    )
