from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import ContractDetails
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract_spec, to_ibapi_contract
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


@dataclass(frozen=True)
class IbkrOvernightAuditResult:
    connected: bool
    base_contract_resolved: bool
    overnight_contract_ready: bool
    symbol: str
    primary_exchange: str | None
    destination: str | None
    order_sent: bool
    message: str


class _OvernightContractProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.ready = Event()
        self.details: list[ContractDetails] = []
        self.fatal_error: str | None = None
        self.errors: list[str] = []

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def contractDetails(self, reqId: int, contractDetails: ContractDetails) -> None:  # noqa: N802
        self.details.append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.ready.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
        message = f"{errorCode}: {errorString}"
        self.errors.append(message)
        if errorCode in {200, 326, 502, 503, 504, 1100}:
            self.fatal_error = message
            self.connected_ready.set()
            self.ready.set()

    def diagnostic_suffix(self) -> str:
        return f" Errors: {' | '.join(self.errors[-5:])}" if self.errors else ""


def audit_ibkr_paper_overnight_contract(
    symbol: str = "SPY",
    *,
    asset_class: AssetClass = AssetClass.ETF,
    config: IbkrConnectionConfig | None = None,
    timeout: float = 8.0,
) -> IbkrOvernightAuditResult:
    """Build an OVERNIGHT contract from broker-resolved listing data, read-only."""
    # Current operator environment is TWS Paper on 127.0.0.1:7497.
    # An explicit config can still select Gateway in tests or future deployments.
    cfg = config or create_ibkr_paper_config(use_gateway=False)
    cfg.validate()
    if not cfg.paper_trading or cfg.allow_live_trading:
        raise RuntimeError("Overnight audit requires Paper Trading with Live disabled.")

    normalized = symbol.strip().upper()
    base_instrument = InstrumentSpec(normalized, asset_class, exchange="SMART", currency="USD")
    base_contract = to_ibapi_contract(build_ibkr_contract_spec(base_instrument))

    audit_cfg = replace(cfg, client_id=cfg.client_id + 102)
    probe = _OvernightContractProbe()
    try:
        probe.connect(audit_cfg.host, audit_cfg.port, audit_cfg.client_id)
        Thread(target=probe.run, daemon=True).start()
        if not probe.connected_ready.wait(timeout):
            return IbkrOvernightAuditResult(
                False, False, False, normalized, None, None, False,
                "IBKR Paper API did not become ready before timeout."
                + probe.diagnostic_suffix(),
            )
        if probe.fatal_error:
            return IbkrOvernightAuditResult(
                False, False, False, normalized, None, None, False, probe.fatal_error
            )

        probe.reqContractDetails(1, base_contract)
        probe.ready.wait(timeout)
        if probe.fatal_error:
            return IbkrOvernightAuditResult(
                True, False, False, normalized, None, None, False, probe.fatal_error
            )
        if not probe.details:
            return IbkrOvernightAuditResult(
                True, False, False, normalized, None, None, False,
                "IBKR Paper API returned no base contract details before timeout."
                + probe.diagnostic_suffix(),
            )

        resolved = probe.details[0].contract
        primary = (getattr(resolved, "primaryExchange", "") or "").strip().upper()
        if not primary:
            return IbkrOvernightAuditResult(
                True, True, False, normalized, None, None, False,
                "Broker-resolved contract did not include primaryExchange; overnight routing remains blocked."
                + probe.diagnostic_suffix(),
            )

        overnight_instrument = InstrumentSpec(
            normalized,
            asset_class,
            exchange="OVERNIGHT",
            currency="USD",
            primary_exchange=primary,
        )
        overnight_contract = to_ibapi_contract(build_ibkr_contract_spec(overnight_instrument))
        return IbkrOvernightAuditResult(
            True, True, True, normalized,
            overnight_contract.primaryExchange,
            overnight_contract.exchange,
            False,
            "Overnight contract routing fields are ready. No order was created or transmitted."
            + probe.diagnostic_suffix(),
        )
    finally:
        if probe.isConnected():
            probe.disconnect()


def main() -> int:
    result = audit_ibkr_paper_overnight_contract()
    print("===== IBKR PAPER OVERNIGHT CONTRACT AUDIT =====")
    print("CONNECTED              :", result.connected)
    print("BASE CONTRACT RESOLVED :", result.base_contract_resolved)
    print("OVERNIGHT CONTRACT READY:", result.overnight_contract_ready)
    print("SYMBOL                 :", result.symbol)
    print("PRIMARY EXCHANGE       :", result.primary_exchange)
    print("DESTINATION            :", result.destination)
    print("ORDER SENT             :", result.order_sent)
    print("MESSAGE                :", result.message)
    return 0 if result.overnight_contract_ready and not result.order_sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
