"""Read-only IBKR Paper FX conversion evidence.

The preferred source is a CASH/IDEALPRO bid/ask snapshot. Paper market data can
be unavailable with IBKR error 10197 when a competing live session owns market
data. In that case this module may fall back to the Paper account's own
``ExchangeRate`` account value, which IBKR defines as the exchange rate of that
currency into the account base currency. Neither path creates or transmits an
Order. If neither broker-provided source proves a positive rate, the result
fails closed.
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
    source: str = "MARKET_DATA"
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.connected and self.rate is not None and self.rate > 0 and not self.order_sent


def _parse_error(args: tuple[object, ...]) -> tuple[int, str] | None:
    """Normalize legacy/newer ibapi EWrapper.error callback shapes."""
    if len(args) >= 4:
        error_code = args[1]
        error_string = args[2]
    elif len(args) >= 2:
        error_code = args[0]
        error_string = args[1]
    else:
        return None
    try:
        return int(error_code), str(error_string)
    except (TypeError, ValueError):
        return None


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
        if int(tickType) == 1:
            self.bid = value
        elif int(tickType) == 2:
            self.ask = value

    def tickSnapshotEnd(self, reqId: int) -> None:  # noqa: N802
        self.snapshot_ready.set()

    def error(self, reqId, *args):
        parsed = _parse_error(args)
        if parsed is None:
            return
        normalized_code, error_string = parsed
        message = f"{normalized_code}: {error_string}"
        self.errors.append(message)
        if normalized_code in {200, 326, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.snapshot_ready.set()


class _AccountFxProbe(EWrapper, EClient):
    """Read one IBKR account ExchangeRate without a market-data subscription."""

    def __init__(self, *, currency: str) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.currency = str(currency).strip().upper()
        self.connected_ready = Event()
        self.account_ready = Event()
        self.fx_ready = Event()
        self.account_id: str | None = None
        self.rate: float | None = None
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        accounts = [item.strip() for item in str(accountsList).split(",") if item.strip()]
        if accounts:
            self.account_id = accounts[0]
        self.account_ready.set()

    def updateAccountValue(self, key: str, val: str, currency: str, accountName: str) -> None:  # noqa: N802
        if str(key).strip() != "ExchangeRate":
            return
        if str(currency).strip().upper() != self.currency:
            return
        try:
            value = float(val)
        except (TypeError, ValueError):
            return
        if value <= 0:
            return
        self.rate = value
        self.fx_ready.set()

    def accountDownloadEnd(self, accountName: str) -> None:  # noqa: N802
        self.fx_ready.set()

    def error(self, reqId, *args):
        parsed = _parse_error(args)
        if parsed is None:
            return
        normalized_code, error_string = parsed
        message = f"{normalized_code}: {error_string}"
        self.errors.append(message)
        if normalized_code in {326, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.account_ready.set()
            self.fx_ready.set()


def _midpoint(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None:
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (float(bid) + float(ask)) / 2.0


def preview_ibkr_paper_account_fx_rate(
    *,
    base_currency: str,
    quote_currency: str,
    timeout: float = 10.0,
) -> IbkrFxSnapshotResult:
    """Read IBKR's account ExchangeRate for ``base_currency`` into base account currency.

    The caller supplies ``quote_currency`` as the expected account/base currency.
    The API value itself is broker-provided account data; no external quote or
    locally guessed conversion is used.
    """
    base = str(base_currency).strip().upper()
    quote = str(quote_currency).strip().upper()
    connection_errors: list[str] = []

    if base == quote:
        return IbkrFxSnapshotResult(
            connected=True,
            endpoint_port=None,
            base_currency=base,
            quote_currency=quote,
            exchange="ACCOUNT",
            bid=1.0,
            ask=1.0,
            rate=1.0,
            source="ACCOUNT_EXCHANGE_RATE",
            order_sent=False,
            errors=(),
        )

    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _AccountFxProbe(currency=base)
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 261)
            except OSError as exc:
                connection_errors.append(f"{cfg.port}: {exc}")
                continue
            Thread(target=probe.run, daemon=True).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                connection_errors.extend(probe.errors)
                continue

            probe.reqManagedAccts()
            if not probe.account_ready.wait(timeout) or not probe.account_id:
                connection_errors.extend(probe.errors)
                connection_errors.append(f"{cfg.port}: managed Paper account unavailable")
                continue

            probe.reqAccountUpdates(True, probe.account_id)
            probe.fx_ready.wait(timeout)
            probe.reqAccountUpdates(False, probe.account_id)
            if probe.rate is None:
                connection_errors.extend(probe.errors)
                connection_errors.append(
                    f"{cfg.port}: account ExchangeRate for {base}->{quote} unavailable"
                )
                continue

            return IbkrFxSnapshotResult(
                connected=True,
                endpoint_port=cfg.port,
                base_currency=base,
                quote_currency=quote,
                exchange="ACCOUNT",
                bid=None,
                ask=None,
                rate=probe.rate,
                source="ACCOUNT_EXCHANGE_RATE",
                order_sent=False,
                errors=tuple(connection_errors + probe.errors),
            )
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrFxSnapshotResult(
        connected=False,
        endpoint_port=None,
        base_currency=base,
        quote_currency=quote,
        exchange="ACCOUNT",
        bid=None,
        ask=None,
        rate=None,
        source="ACCOUNT_EXCHANGE_RATE",
        order_sent=False,
        errors=tuple(connection_errors),
    )


def preview_ibkr_paper_fx_rate(
    *,
    base_currency: str,
    quote_currency: str,
    exchange: str = "IDEALPRO",
    timeout: float = 10.0,
) -> IbkrFxSnapshotResult:
    """Request broker FX evidence, preferring bid/ask and falling back to account data."""
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
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 260)
            except OSError as exc:
                connection_errors.append(f"{cfg.port}: {exc}")
                continue
            Thread(target=probe.run, daemon=True).start()
            ready = probe.connected_ready.wait(timeout)
            if not ready or probe.fatal_error:
                connection_errors.extend(probe.errors)
                continue

            probe.reqMktData(1, contract, "", True, False, [])
            probe.snapshot_ready.wait(timeout)
            rate = _midpoint(probe.bid, probe.ask)
            if rate is not None:
                return IbkrFxSnapshotResult(
                    connected=True,
                    endpoint_port=cfg.port,
                    base_currency=contract.symbol,
                    quote_currency=contract.currency,
                    exchange=contract.exchange,
                    bid=probe.bid,
                    ask=probe.ask,
                    rate=rate,
                    source="MARKET_DATA",
                    order_sent=False,
                    errors=tuple(connection_errors + probe.errors),
                )
            connection_errors.extend(probe.errors)
        finally:
            if probe.isConnected():
                probe.disconnect()

    # Error 10197 and missing bid/ask must not force an operator to close another
    # session merely to obtain an accounting conversion. Ask the same Paper
    # account for IBKR's own ExchangeRate value instead; this is account data,
    # not a market-data subscription and never transmits an order.
    fallback = preview_ibkr_paper_account_fx_rate(
        base_currency=contract.symbol,
        quote_currency=contract.currency,
        timeout=timeout,
    )
    return IbkrFxSnapshotResult(
        connected=fallback.connected,
        endpoint_port=fallback.endpoint_port,
        base_currency=fallback.base_currency,
        quote_currency=fallback.quote_currency,
        exchange=fallback.exchange,
        bid=fallback.bid,
        ask=fallback.ask,
        rate=fallback.rate,
        source=fallback.source,
        order_sent=False,
        errors=tuple(connection_errors + list(fallback.errors)),
    )
