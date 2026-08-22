"""Read-only IBKR Paper FX conversion evidence.

The preferred source is a CASH/IDEALPRO bid/ask snapshot. Paper market data can
be unavailable with IBKR error 10197 when another session owns live market data.
This module therefore tries three broker-only read paths, in order:

1. live market-data snapshot,
2. delayed market-data snapshot (still read-only and broker-provided),
3. account ExchangeRate data (AccountSummary, then legacy account updates).

No path creates, changes, cancels, or transmits an Order. If no positive broker-
provided rate is available, the result fails closed.
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
        # bid/ask plus delayed bid/ask tick types
        if int(tickType) in {1, 66}:
            self.bid = value
        elif int(tickType) in {2, 67}:
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


class _AccountSummaryFxProbe(EWrapper, EClient):
    def __init__(self, *, currency: str) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.currency = str(currency).strip().upper()
        self.connected_ready = Event()
        self.summary_ready = Event()
        self.rate: float | None = None
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def accountSummary(self, reqId, account, tag, value, currency):  # noqa: N802
        if str(tag).strip() != "ExchangeRate":
            return
        if str(currency).strip().upper() != self.currency:
            return
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return
        if parsed <= 0:
            return
        self.rate = parsed
        self.summary_ready.set()

    def accountSummaryEnd(self, reqId: int) -> None:  # noqa: N802
        self.summary_ready.set()

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
            self.summary_ready.set()


class _AccountFxProbe(EWrapper, EClient):
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


def _request_market_snapshot(
    contract: Contract,
    *,
    delayed: bool,
    timeout: float,
) -> IbkrFxSnapshotResult:
    errors: list[str] = []
    source = "DELAYED_MARKET_DATA" if delayed else "MARKET_DATA"
    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _FxSnapshotProbe()
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + (263 if delayed else 260))
            except OSError as exc:
                errors.append(f"{cfg.port}: {exc}")
                continue
            Thread(target=probe.run, daemon=True).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                errors.extend(probe.errors)
                continue
            if delayed:
                # 3 = delayed market data. Read-only; does not create an order.
                probe.reqMarketDataType(3)
            probe.reqMktData(1, contract, "", True, False, [])
            probe.snapshot_ready.wait(timeout)
            rate = _midpoint(probe.bid, probe.ask)
            if rate is not None:
                return IbkrFxSnapshotResult(
                    True, cfg.port, contract.symbol, contract.currency,
                    contract.exchange, probe.bid, probe.ask, rate, source, False,
                    tuple(errors + probe.errors),
                )
            errors.extend(probe.errors)
        finally:
            if probe.isConnected():
                probe.disconnect()
    return IbkrFxSnapshotResult(
        False, None, contract.symbol, contract.currency, contract.exchange,
        None, None, None, source, False, tuple(errors),
    )


def preview_ibkr_paper_account_summary_fx_rate(
    *, base_currency: str, quote_currency: str, timeout: float = 10.0
) -> IbkrFxSnapshotResult:
    base = str(base_currency).strip().upper()
    quote = str(quote_currency).strip().upper()
    errors: list[str] = []
    if base == quote:
        return IbkrFxSnapshotResult(True, None, base, quote, "ACCOUNT_SUMMARY", 1.0, 1.0, 1.0, "ACCOUNT_SUMMARY_EXCHANGE_RATE", False, ())
    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _AccountSummaryFxProbe(currency=base)
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 262)
            except OSError as exc:
                errors.append(f"{cfg.port}: {exc}")
                continue
            Thread(target=probe.run, daemon=True).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                errors.extend(probe.errors)
                continue
            req_id = 1
            probe.reqAccountSummary(req_id, "All", "ExchangeRate")
            probe.summary_ready.wait(timeout)
            try:
                probe.cancelAccountSummary(req_id)
            except Exception:
                pass
            if probe.rate is not None:
                return IbkrFxSnapshotResult(True, cfg.port, base, quote, "ACCOUNT_SUMMARY", None, None, probe.rate, "ACCOUNT_SUMMARY_EXCHANGE_RATE", False, tuple(errors + probe.errors))
            errors.extend(probe.errors)
            errors.append(f"{cfg.port}: account summary ExchangeRate for {base}->{quote} unavailable")
        finally:
            if probe.isConnected():
                probe.disconnect()
    return IbkrFxSnapshotResult(False, None, base, quote, "ACCOUNT_SUMMARY", None, None, None, "ACCOUNT_SUMMARY_EXCHANGE_RATE", False, tuple(errors))


def preview_ibkr_paper_account_fx_rate(*, base_currency: str, quote_currency: str, timeout: float = 10.0) -> IbkrFxSnapshotResult:
    base = str(base_currency).strip().upper()
    quote = str(quote_currency).strip().upper()
    errors: list[str] = []
    if base == quote:
        return IbkrFxSnapshotResult(True, None, base, quote, "ACCOUNT", 1.0, 1.0, 1.0, "ACCOUNT_EXCHANGE_RATE", False, ())
    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _AccountFxProbe(currency=base)
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 261)
            except OSError as exc:
                errors.append(f"{cfg.port}: {exc}")
                continue
            Thread(target=probe.run, daemon=True).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                errors.extend(probe.errors)
                continue
            probe.reqManagedAccts()
            if not probe.account_ready.wait(timeout) or not probe.account_id:
                errors.extend(probe.errors)
                errors.append(f"{cfg.port}: managed Paper account unavailable")
                continue
            probe.reqAccountUpdates(True, probe.account_id)
            probe.fx_ready.wait(timeout)
            probe.reqAccountUpdates(False, probe.account_id)
            if probe.rate is not None:
                return IbkrFxSnapshotResult(True, cfg.port, base, quote, "ACCOUNT", None, None, probe.rate, "ACCOUNT_EXCHANGE_RATE", False, tuple(errors + probe.errors))
            errors.extend(probe.errors)
            errors.append(f"{cfg.port}: account ExchangeRate for {base}->{quote} unavailable")
        finally:
            if probe.isConnected():
                probe.disconnect()
    return IbkrFxSnapshotResult(False, None, base, quote, "ACCOUNT", None, None, None, "ACCOUNT_EXCHANGE_RATE", False, tuple(errors))


def preview_ibkr_paper_fx_rate(*, base_currency: str, quote_currency: str, exchange: str = "IDEALPRO", timeout: float = 10.0) -> IbkrFxSnapshotResult:
    contract: Contract = build_fx_discovery_contract(base_currency=base_currency, quote_currency=quote_currency, exchange=exchange)
    live = _request_market_snapshot(contract, delayed=False, timeout=timeout)
    if live.ready:
        return live

    delayed = _request_market_snapshot(contract, delayed=True, timeout=timeout)
    if delayed.ready:
        return IbkrFxSnapshotResult(
            delayed.connected, delayed.endpoint_port, delayed.base_currency,
            delayed.quote_currency, delayed.exchange, delayed.bid, delayed.ask,
            delayed.rate, delayed.source, False,
            tuple(list(live.errors) + list(delayed.errors)),
        )

    summary = preview_ibkr_paper_account_summary_fx_rate(base_currency=contract.symbol, quote_currency=contract.currency, timeout=timeout)
    if summary.ready:
        return IbkrFxSnapshotResult(summary.connected, summary.endpoint_port, summary.base_currency, summary.quote_currency, summary.exchange, summary.bid, summary.ask, summary.rate, summary.source, False, tuple(list(live.errors) + list(delayed.errors) + list(summary.errors)))

    legacy = preview_ibkr_paper_account_fx_rate(base_currency=contract.symbol, quote_currency=contract.currency, timeout=timeout)
    return IbkrFxSnapshotResult(legacy.connected, legacy.endpoint_port, legacy.base_currency, legacy.quote_currency, legacy.exchange, legacy.bid, legacy.ask, legacy.rate, legacy.source, False, tuple(list(live.errors) + list(delayed.errors) + list(summary.errors) + list(legacy.errors)))
