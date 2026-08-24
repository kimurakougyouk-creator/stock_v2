"""Read-only IBKR option ContractDetails discovery.

This module requires explicit option-defining fields and never creates or sends
an Order. It is an audit-only layer for issue #56 so option capability remains
unverified until product-specific risk, assignment/exercise, sizing and real
Paper E2E evidence are complete.
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
class IbkrOptionCandidate:
    symbol: str
    local_symbol: str | None
    trading_class: str | None
    exchange: str
    currency: str
    expiry: str | None
    strike: float | None
    right: str | None
    multiplier: str | None
    con_id: int | None
    min_tick: float | None
    valid_exchanges: str | None
    order_types: str | None
    time_zone_id: str | None
    trading_hours: str | None
    liquid_hours: str | None


@dataclass(frozen=True)
class IbkrOptionDiscoveryResult:
    connected: bool
    endpoint_port: int | None
    symbol: str
    exchange: str
    currency: str
    candidates: tuple[IbkrOptionCandidate, ...] = field(default_factory=tuple)
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def resolved(self) -> bool:
        return self.connected and bool(self.candidates) and not self.order_sent


class _OptionDiscoveryProbe(EWrapper, EClient):
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


def build_option_discovery_contract(
    *,
    symbol: str,
    exchange: str,
    currency: str,
    expiry: str,
    strike: float,
    right: str,
    multiplier: str | None = None,
) -> Contract:
    normalized_symbol = str(symbol).strip().upper()
    normalized_exchange = str(exchange).strip().upper()
    normalized_currency = str(currency).strip().upper()
    normalized_expiry = str(expiry).strip()
    normalized_right = str(right).strip().upper()
    normalized_multiplier = None if multiplier is None else str(multiplier).strip()

    if not normalized_symbol:
        raise ValueError("option symbol is required")
    if not normalized_exchange:
        raise ValueError("option exchange is required")
    if not normalized_currency:
        raise ValueError("option currency is required")
    if not normalized_expiry:
        raise ValueError("option expiry is required")
    if float(strike) <= 0:
        raise ValueError("option strike must be positive")
    if normalized_right not in {"C", "P"}:
        raise ValueError("option right must be C or P")
    if multiplier is not None and not normalized_multiplier:
        raise ValueError("option multiplier must not be blank when provided")

    contract = Contract()
    contract.symbol = normalized_symbol
    contract.secType = "OPT"
    contract.exchange = normalized_exchange
    contract.currency = normalized_currency
    contract.lastTradeDateOrContractMonth = normalized_expiry
    contract.strike = float(strike)
    contract.right = normalized_right
    if normalized_multiplier is not None:
        contract.multiplier = normalized_multiplier
    return contract


def _candidate(details: ContractDetails) -> IbkrOptionCandidate:
    contract = details.contract
    con_id_value = int(getattr(contract, "conId", 0) or 0)
    min_tick_value = float(getattr(details, "minTick", 0.0) or 0.0)
    strike_value = float(getattr(contract, "strike", 0.0) or 0.0)
    return IbkrOptionCandidate(
        symbol=str(getattr(contract, "symbol", "") or ""),
        local_symbol=(str(getattr(contract, "localSymbol", "") or "") or None),
        trading_class=(str(getattr(contract, "tradingClass", "") or "") or None),
        exchange=str(getattr(contract, "exchange", "") or ""),
        currency=str(getattr(contract, "currency", "") or ""),
        expiry=(
            str(getattr(contract, "lastTradeDateOrContractMonth", "") or "") or None
        ),
        strike=strike_value if strike_value > 0 else None,
        right=(str(getattr(contract, "right", "") or "") or None),
        multiplier=(str(getattr(contract, "multiplier", "") or "") or None),
        con_id=con_id_value if con_id_value > 0 else None,
        min_tick=min_tick_value if min_tick_value > 0 else None,
        valid_exchanges=(str(getattr(details, "validExchanges", "") or "") or None),
        order_types=(str(getattr(details, "orderTypes", "") or "") or None),
        time_zone_id=(str(getattr(details, "timeZoneId", "") or "") or None),
        trading_hours=(str(getattr(details, "tradingHours", "") or "") or None),
        liquid_hours=(str(getattr(details, "liquidHours", "") or "") or None),
    )


def discover_ibkr_paper_option(
    *,
    symbol: str,
    exchange: str,
    currency: str,
    expiry: str,
    strike: float,
    right: str,
    multiplier: str | None = None,
    timeout: float = 10.0,
) -> IbkrOptionDiscoveryResult:
    contract = build_option_discovery_contract(
        symbol=symbol,
        exchange=exchange,
        currency=currency,
        expiry=expiry,
        strike=strike,
        right=right,
        multiplier=multiplier,
    )
    connection_errors: list[str] = []

    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _OptionDiscoveryProbe()
        try:
            probe.connect(cfg.host, cfg.port, cfg.client_id + 250)
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
            return IbkrOptionDiscoveryResult(
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

    return IbkrOptionDiscoveryResult(
        connected=False,
        endpoint_port=None,
        symbol=contract.symbol,
        exchange=contract.exchange,
        currency=contract.currency,
        candidates=(),
        order_sent=False,
        errors=tuple(connection_errors),
    )
