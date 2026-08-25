"""Fail-closed IBKR Paper cryptocurrency What-If permission probe.

This module submits only `whatIf=True` BUY previews for BTC/USD on broker-
resolved PAXOS/ZEROHASH contracts. It never sends a real Paper order and never
enables Live Trading. The probe is intended to distinguish catalog visibility
from broker-side order validation/permission evidence before any real Paper E2E.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_crypto_discovery import discover_ibkr_paper_crypto
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely
from ai_asset_platform.core.settings import SETTINGS

EXCHANGES = ("PAXOS", "ZEROHASH")
WHATIF_CLIENT_OFFSETS = {"PAXOS": 360, "ZEROHASH": 361}
DIAGNOSTIC_CASH_QTY_USD = 25.0


@dataclass(frozen=True)
class CryptoWhatIfVenueResult:
    exchange: str
    connected: bool
    resolved: bool
    preview_received: bool
    endpoint_port: int | None
    con_id: int | None
    local_symbol: str | None
    min_tick: float | None
    min_size: float | None
    size_increment: float | None
    order_types: str | None
    cash_qty_usd: float
    margin_change: float | None
    commission: float | None
    commission_currency: str | None
    warning: str | None
    errors: tuple[str, ...] = field(default_factory=tuple)
    real_order_sent: bool = False
    live_order_sent: bool = False

    @property
    def whatif_accepted(self) -> bool:
        return (
            self.connected
            and self.resolved
            and self.preview_received
            and not self.real_order_sent
            and not self.live_order_sent
        )


@dataclass(frozen=True)
class CryptoWhatIfAuditResult:
    venues: tuple[CryptoWhatIfVenueResult, ...]
    any_whatif_accepted: bool
    account_order_validation_proven: bool
    paper_trading_proven: bool = False
    real_order_sent: bool = False
    live_order_sent: bool = False


class _CryptoWhatIfProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready = Event()
        self.preview = Event()
        self.order_id: int | None = None
        self.margin_change: float | None = None
        self.commission: float | None = None
        self.commission_currency: str | None = None
        self.warning: str | None = None
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.order_id = int(orderId)
        self.ready.set()

    def openOrder(self, orderId, contract, order, orderState):  # noqa: N802
        if not bool(getattr(order, "whatIf", False)):
            return
        try:
            before = float(getattr(orderState, "initMarginBefore", 0.0) or 0.0)
            after = float(getattr(orderState, "initMarginAfter", 0.0) or 0.0)
            self.margin_change = after - before
        except (TypeError, ValueError):
            self.margin_change = None
        try:
            commission = float(getattr(orderState, "commission", 0.0) or 0.0)
            self.commission = commission if commission >= 0 else None
        except (TypeError, ValueError):
            self.commission = None
        self.commission_currency = str(getattr(orderState, "commissionCurrency", "") or "") or None
        self.warning = str(getattr(orderState, "warningText", "") or "") or None
        self.preview.set()

    def error(self, reqId, *args):
        if len(args) >= 3:
            code, text = args[-2], args[-1]
        elif len(args) >= 2:
            code, text = args[0], args[1]
        else:
            return
        message = f"{code}: {text}"
        self.errors.append(message)
        try:
            code_i = int(code)
        except (TypeError, ValueError):
            code_i = 0
        if code_i in {
            200, 201, 202, 321, 322, 323, 326, 502, 503, 504, 1100,
            10287, 10289, 10290, 10292, 10293,
        }:
            self.ready.set()
            self.preview.set()


def _empty(exchange: str, *, errors: tuple[str, ...] = ()) -> CryptoWhatIfVenueResult:
    return CryptoWhatIfVenueResult(
        exchange=exchange,
        connected=False,
        resolved=False,
        preview_received=False,
        endpoint_port=None,
        con_id=None,
        local_symbol=None,
        min_tick=None,
        min_size=None,
        size_increment=None,
        order_types=None,
        cash_qty_usd=DIAGNOSTIC_CASH_QTY_USD,
        margin_change=None,
        commission=None,
        commission_currency=None,
        warning=None,
        errors=errors,
    )


def _run_venue(exchange: str, *, timeout: float) -> CryptoWhatIfVenueResult:
    discovery = discover_ibkr_paper_crypto(
        symbol="BTC", exchange=exchange, currency="USD", timeout=timeout
    )
    exact = [
        item for item in discovery.candidates
        if item.con_id and item.symbol.upper() == "BTC"
        and item.exchange.upper() == exchange and item.currency.upper() == "USD"
    ]
    if not discovery.connected or discovery.endpoint_port is None or len(exact) != 1:
        return _empty(exchange, errors=tuple(discovery.errors))

    candidate = exact[0]
    cfg = create_ibkr_paper_config(use_gateway=(int(discovery.endpoint_port) == 4002))
    probe = _CryptoWhatIfProbe()
    try:
        probe.connect(cfg.host, cfg.port, cfg.client_id + WHATIF_CLIENT_OFFSETS[exchange])
        Thread(
            target=run_ibapi_message_loop_safely,
            kwargs={"client": probe, "errors": probe.errors},
            daemon=True,
        ).start()
        if not probe.ready.wait(timeout) or probe.order_id is None:
            return CryptoWhatIfVenueResult(
                exchange=exchange,
                connected=False,
                resolved=True,
                preview_received=False,
                endpoint_port=cfg.port,
                con_id=candidate.con_id,
                local_symbol=candidate.local_symbol,
                min_tick=candidate.min_tick,
                min_size=candidate.min_size,
                size_increment=candidate.size_increment,
                order_types=candidate.order_types,
                cash_qty_usd=DIAGNOSTIC_CASH_QTY_USD,
                margin_change=None,
                commission=None,
                commission_currency=None,
                warning=None,
                errors=tuple(discovery.errors + tuple(probe.errors)),
            )

        contract = Contract()
        contract.conId = int(candidate.con_id)
        contract.symbol = "BTC"
        contract.secType = "CRYPTO"
        contract.exchange = exchange
        contract.currency = "USD"
        if candidate.local_symbol:
            contract.localSymbol = str(candidate.local_symbol)

        order = Order()
        order.action = "BUY"
        order.orderType = "MKT"
        order.cashQty = DIAGNOSTIC_CASH_QTY_USD
        order.tif = "IOC"
        order.whatIf = True
        order.transmit = True
        order.orderRef = f"stock_v2-crypto-whatif-{exchange.lower()}"
        probe.placeOrder(int(probe.order_id), contract, order)
        probe.preview.wait(timeout)

        hard_reject = any(
            str(error).split(":", 1)[0] in {
                "201", "202", "321", "322", "323", "10287", "10289", "10290", "10292", "10293"
            }
            for error in probe.errors
        )
        return CryptoWhatIfVenueResult(
            exchange=exchange,
            connected=True,
            resolved=True,
            preview_received=bool(probe.preview.is_set() and not hard_reject),
            endpoint_port=cfg.port,
            con_id=candidate.con_id,
            local_symbol=candidate.local_symbol,
            min_tick=candidate.min_tick,
            min_size=candidate.min_size,
            size_increment=candidate.size_increment,
            order_types=candidate.order_types,
            cash_qty_usd=DIAGNOSTIC_CASH_QTY_USD,
            margin_change=probe.margin_change,
            commission=probe.commission,
            commission_currency=probe.commission_currency,
            warning=probe.warning,
            errors=tuple(discovery.errors + tuple(probe.errors)),
        )
    finally:
        if probe.isConnected():
            probe.disconnect()


def run_crypto_whatif_audit(*, timeout: float = 12.0) -> CryptoWhatIfAuditResult:
    if not SETTINGS.enable_ibkr_paper:
        rows = tuple(_empty(exchange, errors=("IBKR Paper is not explicitly enabled",)) for exchange in EXCHANGES)
        return CryptoWhatIfAuditResult(rows, False, False)
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        rows = tuple(_empty(exchange, errors=("Live Trading safety lock is not intact",)) for exchange in EXCHANGES)
        return CryptoWhatIfAuditResult(rows, False, False)

    rows = tuple(_run_venue(exchange, timeout=timeout) for exchange in EXCHANGES)
    accepted = any(row.whatif_accepted for row in rows)
    return CryptoWhatIfAuditResult(
        venues=rows,
        any_whatif_accepted=accepted,
        account_order_validation_proven=accepted,
        paper_trading_proven=False,
        real_order_sent=False,
        live_order_sent=False,
    )


def main() -> int:
    result = run_crypto_whatif_audit()
    print("===== IBKR PAPER CRYPTO WHAT-IF PERMISSION AUDIT =====")
    print("DIAGNOSTIC TARGET       : BTC/USD")
    for row in result.venues:
        print(f"{row.exchange} CONNECTED         :", row.connected)
        print(f"{row.exchange} RESOLVED          :", row.resolved)
        print(f"{row.exchange} PREVIEW RECEIVED  :", row.preview_received)
        print(f"{row.exchange} WHATIF ACCEPTED    :", row.whatif_accepted)
        print(f"{row.exchange} ENDPOINT PORT      :", row.endpoint_port)
        print(f"{row.exchange} CON ID             :", row.con_id)
        print(f"{row.exchange} LOCAL SYMBOL       :", row.local_symbol)
        print(f"{row.exchange} MIN TICK           :", row.min_tick)
        print(f"{row.exchange} MIN SIZE           :", row.min_size)
        print(f"{row.exchange} SIZE INCREMENT     :", row.size_increment)
        print(f"{row.exchange} ORDER TYPES        :", row.order_types)
        print(f"{row.exchange} CASH QTY USD       :", row.cash_qty_usd)
        print(f"{row.exchange} COMMISSION         :", row.commission)
        print(f"{row.exchange} WARNING            :", row.warning)
        print(f"{row.exchange} ERRORS             :", list(row.errors))
    print("ANY WHATIF ACCEPTED     :", result.any_whatif_accepted)
    print("ORDER VALIDATION PROVEN :", result.account_order_validation_proven)
    print("PAPER TRADING PROVEN    :", result.paper_trading_proven)
    print("REAL ORDER SENT         :", result.real_order_sent)
    print("LIVE ORDER SENT         :", result.live_order_sent)
    return 0 if not result.real_order_sent and not result.live_order_sent else 2


if __name__ == "__main__":
    raise SystemExit(main())
