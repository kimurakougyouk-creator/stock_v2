"""Read-only IBKR historical FX fallback for account-currency conversion.

This module requests one short historical MIDPOINT series for a CASH/IDEALPRO
pair. It never creates, changes, cancels, or transmits an order. A usable rate
requires at least one positive close returned by IBKR; otherwise it fails closed.
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
class IbkrHistoricalFxResult:
    connected: bool
    endpoint_port: int | None
    base_currency: str
    quote_currency: str
    exchange: str
    rate: float | None
    source: str = "HISTORICAL_MIDPOINT"
    order_sent: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.connected and self.rate is not None and self.rate > 0 and not self.order_sent


class _HistoricalFxProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.history_ready = Event()
        self.closes: list[float] = []
        self.errors: list[str] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def historicalData(self, reqId, bar):  # noqa: N802
        try:
            close = float(bar.close)
        except (TypeError, ValueError):
            return
        if close > 0:
            self.closes.append(close)

    def historicalDataEnd(self, reqId, start, end):  # noqa: N802
        self.history_ready.set()

    def error(self, reqId, *args):
        if len(args) >= 4:
            code, text = args[1], args[2]
        elif len(args) >= 2:
            code, text = args[0], args[1]
        else:
            return
        try:
            normalized = int(code)
        except (TypeError, ValueError):
            return
        message = f"{normalized}: {text}"
        self.errors.append(message)
        if normalized in {200, 326, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.history_ready.set()


def preview_ibkr_paper_historical_fx_rate(
    *,
    base_currency: str,
    quote_currency: str,
    exchange: str = "IDEALPRO",
    timeout: float = 10.0,
) -> IbkrHistoricalFxResult:
    """Return the most recent broker historical MIDPOINT close, fail closed."""
    contract: Contract = build_fx_discovery_contract(
        base_currency=base_currency,
        quote_currency=quote_currency,
        exchange=exchange,
    )
    errors: list[str] = []

    for use_gateway in (True, False):
        cfg = create_ibkr_paper_config(use_gateway=use_gateway)
        probe = _HistoricalFxProbe()
        try:
            try:
                probe.connect(cfg.host, cfg.port, cfg.client_id + 264)
            except OSError as exc:
                errors.append(f"{cfg.port}: {exc}")
                continue
            Thread(target=probe.run, daemon=True).start()
            if not probe.connected_ready.wait(timeout) or probe.fatal_error:
                errors.extend(probe.errors)
                continue

            probe.reqHistoricalData(
                1,
                contract,
                "",
                "1 D",
                "5 mins",
                "MIDPOINT",
                0,
                2,
                False,
                [],
            )
            probe.history_ready.wait(timeout)
            if probe.closes:
                return IbkrHistoricalFxResult(
                    connected=True,
                    endpoint_port=cfg.port,
                    base_currency=contract.symbol,
                    quote_currency=contract.currency,
                    exchange=contract.exchange,
                    rate=probe.closes[-1],
                    source="HISTORICAL_MIDPOINT",
                    order_sent=False,
                    errors=tuple(errors + probe.errors),
                )
            errors.extend(probe.errors)
            errors.append(f"{cfg.port}: historical MIDPOINT for {contract.symbol}->{contract.currency} unavailable")
        finally:
            if probe.isConnected():
                probe.disconnect()

    return IbkrHistoricalFxResult(
        connected=False,
        endpoint_port=None,
        base_currency=contract.symbol,
        quote_currency=contract.currency,
        exchange=contract.exchange,
        rate=None,
        source="HISTORICAL_MIDPOINT",
        order_sent=False,
        errors=tuple(errors),
    )
