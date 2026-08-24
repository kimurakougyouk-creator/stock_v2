"""Read-only IBKR global stock contract discovery.

This module deliberately stops at ContractDetails. It does not choose a Paper
pilot quantity, create an Order, or transmit anything. The caller must provide
an explicit symbol/exchange/currency tuple so non-US stocks are never inferred
from ticker punctuation or a market-wide default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event

from ibapi.client import EClient
from ibapi.contract import Contract, ContractDetails
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_probe_thread import start_guarded_ibapi_loop


@dataclass(frozen=True)
class IbkrGlobalStockCandidate:
    symbol: str
    local_symbol: str | None
    exchange: str
    primary_exchange: str | None
    currency: str
    con_id: int | None
    min_tick: float | None
    min_size: float | None
    size_increment: float | None
    suggested_size_increment: float | None
    valid_exchanges: str | None
    order_types: str | None
    time_zone_id: str | None
    trading_hours: str | None
    liquid_hours: str | None


@dataclass(frozen=True)
class IbkrGlobalStockDiscoveryResult:
    connected: bool
    endpoint_port: int | None
    symbol: str
    exchange: str
    currency: str
    candidates: tuple[IbkrGlobalStockCandidate, ...] = field(default_factory=tuple)
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        return self.connected and bool(self.candidates) and not self.order_sent


class _GlobalStockProbe(EWrapper, EClient):
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


def build_global_stock_discovery_contract(*, symbol: str, exchange: str, currency: str) -> Contract:
    normalized_symbol = str(symbol).strip().upper()
    normalized_exchange = str(exchange).strip().upper()
    normalized_currency = str(currency).strip().upper()
    if not normalized_symbol:
        raise ValueError("stock symbol is required")
    if not normalized_exchange:
        raise ValueError("stock exchange is required")
    if not normalized_currency:
        raise ValueError("stock currency is required")
    contract = Contract()
    contract.symbol = normalized_symbol
    contract.secType = "STK"
    contract.exchange = normalized_exchange
    contract.currency = normalized_currency
    return contract


def _positive_optional(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _candidate(details: ContractDetails) -> IbkrGlobalStockCandidate:
    contract = details.contract
    con_id_value = int(getattr(contract, "conId", 0) or 0)
    return IbkrGlobalStockCandidate(
        symbol=str(getattr(contract, "symbol", "") or ""),
        local_symbol=(str(getattr(contract, "localSymbol", "") or "") or None),
        exchange=str(getattr(contract, "exchange", "") or ""),
        primary_exchange=(str(getattr(contract, "primaryExchange", "") or "") or None),
        currency=str(getattr(contract, "currency", "") or ""),
        con_id=con_id_value if con_id_value > 0 else None,
        min_tick=_positive_optional(getattr(details, "minTick", None)),
        min_size=_positive_optional(getattr(details, "minSize", None)),
        size_increment=_positive_optional(getattr(details, "sizeIncrement", None)),
        suggested_size_increment=_positive_optional(getattr(details, "suggestedSizeIncrement", None)),
        valid_exchanges=(str(getattr(details, "validExchanges", "") or "") or None),
        order_types=(str(getattr(details, "orderTypes", "") or "") or None),
        time_zone_id=(str(getattr(details, "timeZoneId", "") or "") or None),
        trading_hours=(str(getattr(details, "tradingHours", "") or "") or None),
        liquid_hours=(str(getattr(details, "liquidHours", "") or "") or None),
    )


def discover_ibkr_paper_global_stock(
    *, symbol: str, exchange: str, currency: str, timeout: float = 10.0
) -> IbkrGlobalStockDiscoveryResult:
    """Resolve an explicit non-US/global stock through Paper ContractDetails only."""
    contract = build_global_stock_discovery_contract(
        symbol=symbol, exchange=exchange, currency=currency
    )
    connection_errors: list[str] = []
    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _GlobalStockProbe()
        thread = None
        thread_state = None
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 230)
            except OSError as exc:
                connection_errors.append(f"{cfg.port}: {exc}")
                continue
            thread, thread_state = start_guarded_ibapi_loop(
                probe.run,
                name=f"ibkr-global-stock-{cfg.port}",
            )
            ready = probe.connected_ready.wait(timeout)
            if not ready or probe.fatal_error:
                if thread_state.exception:
                    connection_errors.append(f"{cfg.port}: message-loop {thread_state.exception}")
                connection_errors.extend(probe.errors)
                continue
            probe.reqContractDetails(1, contract)
            probe.details_ready.wait(timeout)
            candidates = tuple(_candidate(item) for item in probe.details)
            return IbkrGlobalStockDiscoveryResult(
                connected=True, endpoint_port=cfg.port,
                symbol=contract.symbol, exchange=contract.exchange, currency=contract.currency,
                candidates=candidates, order_sent=False,
                errors=tuple(connection_errors + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()
            if thread is not None:
                thread.join(timeout=1.0)
    return IbkrGlobalStockDiscoveryResult(
        connected=False, endpoint_port=None,
        symbol=contract.symbol, exchange=contract.exchange, currency=contract.currency,
        candidates=(), order_sent=False, errors=tuple(connection_errors),
    )
