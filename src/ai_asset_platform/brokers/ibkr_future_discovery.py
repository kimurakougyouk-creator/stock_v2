"""Read-only IBKR futures discovery foundation.

This module deliberately stops before any futures order path. It discovers
ContractDetails for a symbol/exchange/currency tuple and records broker-returned
expiry, multiplier, tick size and trading hours. No Order object is created and
no verified Paper quantity is assigned.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import Contract, ContractDetails
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config


@dataclass(frozen=True)
class IbkrFutureCandidate:
    symbol: str
    local_symbol: str | None
    exchange: str
    currency: str
    expiry: str | None
    multiplier: str | None
    con_id: int | None
    min_tick: float | None
    time_zone_id: str | None
    trading_hours: str | None
    liquid_hours: str | None


@dataclass(frozen=True)
class IbkrFutureDiscoveryResult:
    connected: bool
    endpoint_port: int | None
    symbol: str
    exchange: str
    currency: str
    candidates: tuple[IbkrFutureCandidate, ...] = field(default_factory=tuple)
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        return self.connected and bool(self.candidates) and not self.order_sent


class _FutureDiscoveryProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.details_ready = Event()
        self.details: list[ContractDetails] = []
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def contractDetails(self, reqId: int, contractDetails: ContractDetails) -> None:  # noqa: N802
        self.details.append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.details_ready.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
        message = f"{errorCode}: {errorString}"
        self.errors.append(message)
        if errorCode in {200, 326, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.details_ready.set()


def build_future_discovery_contract(
    *,
    symbol: str,
    exchange: str,
    currency: str = "USD",
) -> Contract:
    """Build a broad FUT contract for ContractDetails discovery only."""
    normalized_symbol = str(symbol).strip().upper()
    normalized_exchange = str(exchange).strip().upper()
    normalized_currency = str(currency).strip().upper()
    if not normalized_symbol:
        raise ValueError("future symbol is required")
    if not normalized_exchange:
        raise ValueError("future exchange is required")
    if not normalized_currency:
        raise ValueError("future currency is required")

    contract = Contract()
    contract.symbol = normalized_symbol
    contract.secType = "FUT"
    contract.exchange = normalized_exchange
    contract.currency = normalized_currency
    # No expiry is chosen here: the broker is asked to return candidates.
    return contract


def _candidate(details: ContractDetails) -> IbkrFutureCandidate:
    contract = details.contract
    return IbkrFutureCandidate(
        symbol=str(getattr(contract, "symbol", "") or ""),
        local_symbol=(str(getattr(contract, "localSymbol", "") or "") or None),
        exchange=str(getattr(contract, "exchange", "") or ""),
        currency=str(getattr(contract, "currency", "") or ""),
        expiry=(
            str(getattr(contract, "lastTradeDateOrContractMonth", "") or "")
            or None
        ),
        multiplier=(str(getattr(contract, "multiplier", "") or "") or None),
        con_id=(
            int(getattr(contract, "conId", 0))
            if int(getattr(contract, "conId", 0) or 0) > 0
            else None
        ),
        min_tick=(
            float(getattr(details, "minTick", 0.0))
            if float(getattr(details, "minTick", 0.0) or 0.0) > 0
            else None
        ),
        time_zone_id=(str(getattr(details, "timeZoneId", "") or "") or None),
        trading_hours=(str(getattr(details, "tradingHours", "") or "") or None),
        liquid_hours=(str(getattr(details, "liquidHours", "") or "") or None),
    )


def discover_ibkr_paper_futures(
    *,
    symbol: str,
    exchange: str,
    currency: str = "USD",
    timeout: float = 10.0,
) -> IbkrFutureDiscoveryResult:
    """Discover FUT ContractDetails through Paper API without placing an order.

    Gateway Paper 4002 is tried first, then TWS Paper 7497. Endpoint fallback
    occurs only before ContractDetails is requested. Once a session accepts the
    connection, no second endpoint is used for that discovery attempt.
    """
    contract = build_future_discovery_contract(
        symbol=symbol, exchange=exchange, currency=currency
    )
    normalized_symbol = contract.symbol
    normalized_exchange = contract.exchange
    normalized_currency = contract.currency
    connection_errors: list[str] = []

    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _FutureDiscoveryProbe()
        try:
            probe.connect(cfg.host, cfg.port, cfg.client_id + 220)
            Thread(target=probe.run, daemon=True).start()
            ready = probe.connected_ready.wait(timeout)
            if not ready or probe.fatal_error:
                connection_errors.extend(probe.errors)
                if probe.isConnected():
                    probe.disconnect()
                continue

            probe.reqContractDetails(1, contract)
            probe.details_ready.wait(timeout)
            candidates = tuple(_candidate(item) for item in probe.details)
            return IbkrFutureDiscoveryResult(
                connected=True,
                endpoint_port=cfg.port,
                symbol=normalized_symbol,
                exchange=normalized_exchange,
                currency=normalized_currency,
                candidates=candidates,
                order_sent=False,
                errors=tuple(connection_errors + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrFutureDiscoveryResult(
        connected=False,
        endpoint_port=None,
        symbol=normalized_symbol,
        exchange=normalized_exchange,
        currency=normalized_currency,
        candidates=(),
        order_sent=False,
        errors=tuple(connection_errors),
    )
