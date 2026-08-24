"""Read-only IBKR Paper option-chain discovery for SPY.

Resolves the SPY stock contract first, then requests security-definition option
parameters. No Order object is created and no Paper or Live order can be sent.
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
class OptionChainCandidate:
    exchange: str
    underlying_con_id: int
    trading_class: str
    multiplier: str
    expirations: tuple[str, ...]
    strikes: tuple[float, ...]


@dataclass(frozen=True)
class OptionChainDiscoveryResult:
    connected: bool
    endpoint_port: int | None
    underlying_symbol: str
    underlying_con_id: int | None
    candidates: tuple[OptionChainCandidate, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)
    order_sent: bool = False

    @property
    def ready(self) -> bool:
        return self.connected and self.underlying_con_id is not None and bool(self.candidates) and not self.order_sent


class _Probe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.contract_ready = Event()
        self.option_ready = Event()
        self.contracts: list[ContractDetails] = []
        self.params: list[OptionChainCandidate] = []
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def contractDetails(self, reqId, contractDetails):  # noqa: N802
        self.contracts.append(contractDetails)

    def contractDetailsEnd(self, reqId):  # noqa: N802
        self.contract_ready.set()

    def securityDefinitionOptionParameter(self, reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes):  # noqa: N802,E501
        self.params.append(
            OptionChainCandidate(
                exchange=str(exchange or "").strip().upper(),
                underlying_con_id=int(underlyingConId or 0),
                trading_class=str(tradingClass or "").strip().upper(),
                multiplier=str(multiplier or "").strip(),
                expirations=tuple(sorted(str(x) for x in expirations if str(x).strip())),
                strikes=tuple(sorted(float(x) for x in strikes if float(x) > 0)),
            )
        )

    def securityDefinitionOptionParameterEnd(self, reqId):  # noqa: N802
        self.option_ready.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
        self.errors.append(f"{errorCode}: {errorString}")
        if int(errorCode) in {200, 326, 502, 503, 504, 1100}:
            self.connected_ready.set()
            self.contract_ready.set()
            self.option_ready.set()


def _spy_contract() -> Contract:
    c = Contract()
    c.symbol = "SPY"
    c.secType = "STK"
    c.exchange = "SMART"
    c.currency = "USD"
    c.primaryExchange = "ARCA"
    return c


def discover_spy_option_chain(*, timeout: float = 12.0) -> OptionChainDiscoveryResult:
    cfg = create_ibkr_paper_config(use_gateway=True)
    probe = _Probe()
    try:
        probe.connect(cfg.host, cfg.port, cfg.client_id + 300)
        start_guarded_ibapi_loop(probe.run, name="ibkr-option-chain-discovery")
        if not probe.connected_ready.wait(timeout):
            return OptionChainDiscoveryResult(False, cfg.port, "SPY", None, errors=tuple(probe.errors))
        probe.reqContractDetails(1, _spy_contract())
        if not probe.contract_ready.wait(timeout):
            return OptionChainDiscoveryResult(True, cfg.port, "SPY", None, errors=tuple(probe.errors))
        exact = [d.contract for d in probe.contracts if str(getattr(d.contract, "symbol", "")).upper() == "SPY" and str(getattr(d.contract, "secType", "")).upper() == "STK" and int(getattr(d.contract, "conId", 0) or 0) > 0]
        if len(exact) != 1:
            return OptionChainDiscoveryResult(True, cfg.port, "SPY", None, errors=tuple(probe.errors))
        con_id = int(exact[0].conId)
        probe.reqSecDefOptParams(2, "SPY", "", "STK", con_id)
        probe.option_ready.wait(timeout)
        return OptionChainDiscoveryResult(True, cfg.port, "SPY", con_id, tuple(probe.params), tuple(probe.errors), False)
    finally:
        if probe.isConnected():
            probe.disconnect()


def main() -> int:
    result = discover_spy_option_chain()
    print("===== IBKR PAPER SPY OPTION CHAIN READ-ONLY AUDIT =====")
    print("CONNECTED            :", result.connected)
    print("ENDPOINT PORT        :", result.endpoint_port)
    print("UNDERLYING           :", result.underlying_symbol)
    print("UNDERLYING CON ID    :", result.underlying_con_id)
    print("CHAIN CANDIDATE COUNT:", len(result.candidates))
    for i, item in enumerate(result.candidates, 1):
        exps = list(item.expirations[:6])
        strikes = list(item.strikes[:12])
        print(f"CHAIN {i}: exchange={item.exchange or 'UNKNOWN'} trading_class={item.trading_class or 'UNKNOWN'} multiplier={item.multiplier or 'UNKNOWN'} expirations={exps} strike_sample={strikes} strike_count={len(item.strikes)}")
    print("ERRORS               :", list(result.errors))
    print("REAL ORDER SENT      : False")
    print("LIVE ORDER SENT      : False")
    return 0 if result.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
