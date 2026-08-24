"""Read-only IBKR cryptocurrency ContractDetails discovery.

The TWS API documents CRYPTO contracts, but account/region permissions are not
assumed here. The caller must provide symbol, exchange and currency explicitly.
This module never creates or transmits an Order and never promotes a verified
Paper capability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import Contract, ContractDetails
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely


@dataclass(frozen=True)
class IbkrCryptoCandidate:
    symbol: str
    exchange: str
    currency: str
    local_symbol: str | None
    con_id: int | None
    min_tick: float | None
    valid_exchanges: str | None
    order_types: str | None
    time_zone_id: str | None
    trading_hours: str | None
    liquid_hours: str | None


@dataclass(frozen=True)
class IbkrCryptoDiscoveryResult:
    connected: bool
    endpoint_port: int | None
    symbol: str
    exchange: str
    currency: str
    candidates: tuple[IbkrCryptoCandidate, ...] = field(default_factory=tuple)
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        return self.connected and bool(self.candidates) and not self.order_sent


class _CryptoDiscoveryProbe(EWrapper, EClient):
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


def build_crypto_discovery_contract(*, symbol: str, exchange: str, currency: str) -> Contract:
    normalized_symbol = str(symbol).strip().upper()
    normalized_exchange = str(exchange).strip().upper()
    normalized_currency = str(currency).strip().upper()
    if not normalized_symbol:
        raise ValueError("crypto symbol is required")
    if not normalized_exchange:
        raise ValueError("crypto exchange is required")
    if not normalized_currency:
        raise ValueError("crypto currency is required")

    contract = Contract()
    contract.symbol = normalized_symbol
    contract.secType = "CRYPTO"
    contract.exchange = normalized_exchange
    contract.currency = normalized_currency
    return contract


def _candidate(details: ContractDetails) -> IbkrCryptoCandidate:
    contract = details.contract
    con_id_value = int(getattr(contract, "conId", 0) or 0)
    min_tick_value = float(getattr(details, "minTick", 0.0) or 0.0)
    return IbkrCryptoCandidate(
        symbol=str(getattr(contract, "symbol", "") or ""),
        exchange=str(getattr(contract, "exchange", "") or ""),
        currency=str(getattr(contract, "currency", "") or ""),
        local_symbol=(str(getattr(contract, "localSymbol", "") or "") or None),
        con_id=con_id_value if con_id_value > 0 else None,
        min_tick=min_tick_value if min_tick_value > 0 else None,
        valid_exchanges=(str(getattr(details, "validExchanges", "") or "") or None),
        order_types=(str(getattr(details, "orderTypes", "") or "") or None),
        time_zone_id=(str(getattr(details, "timeZoneId", "") or "") or None),
        trading_hours=(str(getattr(details, "tradingHours", "") or "") or None),
        liquid_hours=(str(getattr(details, "liquidHours", "") or "") or None),
    )


def discover_ibkr_paper_crypto(
    *,
    symbol: str,
    exchange: str,
    currency: str,
    timeout: float = 10.0,
) -> IbkrCryptoDiscoveryResult:
    contract = build_crypto_discovery_contract(
        symbol=symbol, exchange=exchange, currency=currency
    )
    connection_errors: list[str] = []

    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _CryptoDiscoveryProbe()
        try:
            probe.connect(cfg.host, cfg.port, cfg.client_id + 260)
            Thread(
                target=run_ibapi_message_loop_safely,
                kwargs={"client": probe, "errors": probe.errors},
                daemon=True,
            ).start()
            ready = probe.connected_ready.wait(timeout)
            if not ready or probe.fatal_error:
                connection_errors.extend(probe.errors)
                continue

            probe.reqContractDetails(1, contract)
            probe.details_ready.wait(timeout)
            candidates = tuple(_candidate(item) for item in probe.details)
            return IbkrCryptoDiscoveryResult(
                connected=True,
                endpoint_port=cfg.port,
                symbol=contract.symbol,
                exchange=contract.exchange,
                currency=contract.currency,
                candidates=candidates,
                order_sent=False,
                errors=tuple(connection_errors + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrCryptoDiscoveryResult(
        connected=False,
        endpoint_port=None,
        symbol=contract.symbol,
        exchange=contract.exchange,
        currency=contract.currency,
        candidates=(),
        order_sent=False,
        errors=tuple(connection_errors),
    )
