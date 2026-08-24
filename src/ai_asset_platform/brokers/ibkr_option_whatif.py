"""Fail-closed SPY option What-If audit for IBKR Paper.

This module discovers one explicit SPY call option from a small ordered set of
near-dated candidates and submits only an IBKR What-If order. It never enables
Live Trading and never submits a real Paper/Live order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_option_discovery import discover_ibkr_paper_option
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely
from ai_asset_platform.core.settings import SETTINGS

CANDIDATE_EXPIRIES = ("20260828", "20260831")
CANDIDATE_STRIKES = (765.0, 770.0, 760.0, 775.0, 755.0)


@dataclass(frozen=True)
class OptionWhatIfResult:
    connected: bool
    resolved: bool
    preview_received: bool
    endpoint_port: int | None
    local_symbol: str | None
    expiry: str | None
    strike: float | None
    right: str | None
    multiplier: str | None
    con_id: int | None
    margin_change: float | None
    commission: float | None
    commission_currency: str | None
    warning: str | None
    errors: tuple[str, ...] = field(default_factory=tuple)
    real_order_sent: bool = False
    live_order_sent: bool = False

    @property
    def ready(self) -> bool:
        return self.connected and self.resolved and self.preview_received and not self.real_order_sent and not self.live_order_sent


class _WhatIfProbe(EWrapper, EClient):
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
            init_before = float(getattr(orderState, "initMarginBefore", 0.0) or 0.0)
            init_after = float(getattr(orderState, "initMarginAfter", 0.0) or 0.0)
            self.margin_change = init_after - init_before
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
        if code_i in {201, 202, 321, 322, 323, 326, 502, 503, 504, 1100}:
            self.ready.set()
            self.preview.set()


def _resolve_target():
    for expiry in CANDIDATE_EXPIRIES:
        for strike in CANDIDATE_STRIKES:
            result = discover_ibkr_paper_option(
                symbol="SPY",
                exchange="SMART",
                currency="USD",
                expiry=expiry,
                strike=strike,
                right="C",
                multiplier="100",
                timeout=8.0,
            )
            exact = [
                c for c in result.candidates
                if c.con_id and c.local_symbol and c.expiry == expiry
                and c.strike == strike and str(c.right).upper() == "C"
                and str(c.multiplier) == "100"
            ]
            if len(exact) == 1:
                return result.endpoint_port, exact[0], tuple(result.errors)
    return None, None, ()


def run_option_whatif_for_candidate(
    endpoint_port: int,
    candidate,
    *,
    timeout: float = 15.0,
    discovery_errors: tuple[str, ...] = (),
) -> OptionWhatIfResult:
    """Submit a What-If for one already-resolved exact candidate only."""
    if not SETTINGS.enable_ibkr_paper:
        return OptionWhatIfResult(False, False, False, endpoint_port, None, None, None, None, None, None, None, None, None, "IBKR Paper is not explicitly enabled")
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return OptionWhatIfResult(False, False, False, endpoint_port, None, None, None, None, None, None, None, None, None, "Live Trading safety lock is not intact")
    if candidate is None or not getattr(candidate, "con_id", None) or not getattr(candidate, "local_symbol", None):
        return OptionWhatIfResult(False, False, False, endpoint_port, None, None, None, None, None, None, None, None, None, None, discovery_errors)

    cfg = create_ibkr_paper_config(use_gateway=(int(endpoint_port) == 4002))
    probe = _WhatIfProbe()
    try:
        probe.connect(cfg.host, cfg.port, cfg.client_id + 295)
        Thread(target=run_ibapi_message_loop_safely, kwargs={"client": probe, "errors": probe.errors}, daemon=True).start()
        if not probe.ready.wait(timeout) or probe.order_id is None:
            return OptionWhatIfResult(False, True, False, cfg.port, candidate.local_symbol, candidate.expiry, candidate.strike, candidate.right, candidate.multiplier, candidate.con_id, None, None, None, None, tuple(discovery_errors + tuple(probe.errors)))

        contract = __import__("ibapi.contract", fromlist=["Contract"]).Contract()
        contract.conId = int(candidate.con_id)
        contract.symbol = "SPY"
        contract.secType = "OPT"
        contract.exchange = "SMART"
        contract.currency = "USD"
        contract.localSymbol = str(candidate.local_symbol)
        contract.lastTradeDateOrContractMonth = str(candidate.expiry)
        contract.strike = float(candidate.strike)
        contract.right = str(candidate.right)
        contract.multiplier = str(candidate.multiplier)

        order = Order()
        order.action = "BUY"
        order.orderType = "LMT"
        order.totalQuantity = 1
        order.lmtPrice = 0.01
        order.tif = "DAY"
        order.whatIf = True
        order.transmit = True
        order.orderRef = "stock_v2-option-whatif"
        probe.placeOrder(int(probe.order_id), contract, order)
        probe.preview.wait(timeout)

        return OptionWhatIfResult(
            connected=True,
            resolved=True,
            preview_received=probe.preview.is_set() and not any(str(e).startswith("201:") for e in probe.errors),
            endpoint_port=cfg.port,
            local_symbol=candidate.local_symbol,
            expiry=candidate.expiry,
            strike=candidate.strike,
            right=candidate.right,
            multiplier=candidate.multiplier,
            con_id=candidate.con_id,
            margin_change=probe.margin_change,
            commission=probe.commission,
            commission_currency=probe.commission_currency,
            warning=probe.warning,
            errors=tuple(discovery_errors + tuple(probe.errors)),
            real_order_sent=False,
            live_order_sent=False,
        )
    finally:
        if probe.isConnected():
            probe.disconnect()


def run_option_whatif(*, timeout: float = 15.0) -> OptionWhatIfResult:
    if not SETTINGS.enable_ibkr_paper:
        return OptionWhatIfResult(False, False, False, None, None, None, None, None, None, None, None, None, None, "IBKR Paper is not explicitly enabled")
    if SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked:
        return OptionWhatIfResult(False, False, False, None, None, None, None, None, None, None, None, None, None, "Live Trading safety lock is not intact")

    endpoint_port, candidate, discovery_errors = _resolve_target()
    if candidate is None or endpoint_port is None:
        return OptionWhatIfResult(False, False, False, endpoint_port, None, None, None, None, None, None, None, None, None, None, discovery_errors)
    return run_option_whatif_for_candidate(
        endpoint_port,
        candidate,
        timeout=timeout,
        discovery_errors=discovery_errors,
    )


def main() -> int:
    result = run_option_whatif()
    print("===== IBKR PAPER SPY OPTION WHAT-IF =====")
    print("CONNECTED             :", result.connected)
    print("RESOLVED              :", result.resolved)
    print("PREVIEW RECEIVED      :", result.preview_received)
    print("ENDPOINT PORT         :", result.endpoint_port)
    print("LOCAL SYMBOL          :", result.local_symbol)
    print("EXPIRY                :", result.expiry)
    print("STRIKE                :", result.strike)
    print("RIGHT                 :", result.right)
    print("MULTIPLIER            :", result.multiplier)
    print("CON ID                :", result.con_id)
    print("MARGIN CHANGE         :", result.margin_change)
    print("COMMISSION            :", result.commission)
    print("COMMISSION CURRENCY   :", result.commission_currency)
    print("WARNING               :", result.warning)
    print("ERRORS                :", list(result.errors))
    print("READY                 :", result.ready)
    print("REAL ORDER SENT       :", result.real_order_sent)
    print("LIVE ORDER SENT       :", result.live_order_sent)
    return 0 if result.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
