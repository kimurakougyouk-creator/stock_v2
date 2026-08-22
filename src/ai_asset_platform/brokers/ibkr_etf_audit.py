from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.contract import ContractDetails
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_connection import probe_ibkr_paper_connection
from ai_asset_platform.brokers.ibkr_contracts import instrument_to_ibkr_contract
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


@dataclass(frozen=True)
class IbkrEtfAuditResult:
    connected: bool
    contract_resolved: bool
    symbol: str
    sec_type: str | None
    exchange: str | None
    currency: str | None
    order_sent: bool
    message: str


class _ContractDetailsProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.connected_ready = Event()
        self.ready = Event()
        self.details: list[ContractDetails] = []
        self.fatal_error: str | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.connected_ready.set()

    def contractDetails(self, reqId: int, contractDetails: ContractDetails) -> None:  # noqa: N802
        self.details.append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
        self.ready.set()

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
        if errorCode in {200, 326, 502, 503, 504, 1100}:
            self.fatal_error = f"{errorCode}: {errorString}"
            self.connected_ready.set()
            self.ready.set()


def audit_ibkr_paper_etf(
    symbol: str = "SPY",
    *,
    config: IbkrConnectionConfig | None = None,
    timeout: float = 8.0,
) -> IbkrEtfAuditResult:
    """Resolve an ETF through the real Paper API without ever creating or placing an order.

    Contract discovery is intentionally independent of verified order quantity:
    quantity verification is required only before an order can enter the order
    preparation/transmission path. This audit therefore remains safe for an
    unverified product while preserving fail-closed order handling.
    """
    cfg = config or IbkrConnectionConfig()
    cfg.validate()
    if not cfg.paper_trading or cfg.allow_live_trading:
        raise RuntimeError("ETF audit requires Paper Trading with Live disabled.")

    normalized = symbol.strip().upper()
    instrument = InstrumentSpec(normalized, AssetClass.ETF)
    contract = instrument_to_ibkr_contract(instrument)

    connection = probe_ibkr_paper_connection(cfg, timeout=timeout)
    if not connection.connected:
        return IbkrEtfAuditResult(
            False, False, normalized, None, None, None, False, connection.message
        )

    contract_cfg = replace(cfg, client_id=cfg.client_id + 1)
    probe = _ContractDetailsProbe()
    try:
        probe.connect(contract_cfg.host, contract_cfg.port, contract_cfg.client_id)
        thread = Thread(target=probe.run, daemon=True)
        thread.start()

        if not probe.connected_ready.wait(timeout):
            return IbkrEtfAuditResult(
                True, False, normalized, None, None, None, False,
                "IBKR Paper API contract-details session did not become ready before timeout.",
            )
        if probe.fatal_error:
            return IbkrEtfAuditResult(
                True, False, normalized, None, None, None, False, probe.fatal_error
            )

        probe.reqContractDetails(1, contract)
        probe.ready.wait(timeout)

        if probe.fatal_error:
            return IbkrEtfAuditResult(
                True, False, normalized, None, None, None, False, probe.fatal_error
            )
        if not probe.details:
            return IbkrEtfAuditResult(
                True, False, normalized, None, None, None, False,
                "IBKR Paper API returned no contract details before timeout.",
            )

        resolved = probe.details[0].contract
        return IbkrEtfAuditResult(
            True, True, resolved.symbol, resolved.secType, resolved.exchange,
            resolved.currency, False,
            "IBKR Paper API resolved the ETF contract. No order was transmitted.",
        )
    finally:
        if probe.isConnected():
            probe.disconnect()


def main() -> int:
    result = audit_ibkr_paper_etf()
    print("===== IBKR PAPER ETF AUDIT =====")
    print("CONNECTED        :", result.connected)
    print("CONTRACT RESOLVED:", result.contract_resolved)
    print("SYMBOL           :", result.symbol)
    print("SEC TYPE         :", result.sec_type)
    print("EXCHANGE         :", result.exchange)
    print("CURRENCY         :", result.currency)
    print("ORDER SENT       :", result.order_sent)
    print("MESSAGE          :", result.message)
    return 0 if result.connected and result.contract_resolved and not result.order_sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
