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
from ai_asset_platform.brokers.ibkr_connection import probe_ibkr_paper_connection
from ai_asset_platform.brokers.ibkr_contracts import build_ibkr_contract_spec, to_ibapi_contract
from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely
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


def audit_ibkr_paper_etf(
    symbol: str = "SPY",
    *,
    config: IbkrConnectionConfig | None = None,
    timeout: float = 8.0,
) -> IbkrEtfAuditResult:
    """Resolve an ETF through the current TWS Paper API without placing an order."""
    # Current operator environment is TWS Paper on 127.0.0.1:7497.
    # Callers may still pass an explicit config for Gateway or tests.
    cfg = config or create_ibkr_paper_config(use_gateway=False)
    cfg.validate()
    if not cfg.paper_trading or cfg.allow_live_trading:
        raise RuntimeError("ETF audit requires Paper Trading with Live disabled.")

    normalized = symbol.strip().upper()
    instrument = InstrumentSpec(normalized, AssetClass.ETF)
    contract = to_ibapi_contract(build_ibkr_contract_spec(instrument))

    connection = probe_ibkr_paper_connection(cfg, timeout=timeout)
    if not connection.connected:
        return IbkrEtfAuditResult(
            False, False, normalized, None, None, None, False, connection.message
        )

    contract_cfg = replace(cfg, client_id=cfg.client_id + 101)
    probe = _ContractDetailsProbe()
    try:
        probe.connect(contract_cfg.host, contract_cfg.port, contract_cfg.client_id)
        Thread(
            target=run_ibapi_message_loop_safely,
            kwargs={"client": probe, "errors": probe.errors},
            daemon=True,
        ).start()
        if not probe.connected_ready.wait(timeout):
            return IbkrEtfAuditResult(
                True, False, normalized, None, None, None, False,
                "IBKR Paper API contract-details session did not become ready before timeout."
                + probe.diagnostic_suffix(),
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
                "IBKR Paper API returned no contract details before timeout."
                + probe.diagnostic_suffix(),
            )

        resolved = probe.details[0].contract
        return IbkrEtfAuditResult(
            True, True, resolved.symbol, resolved.secType, resolved.exchange,
            resolved.currency, False,
            "IBKR Paper API resolved the ETF contract. No order was transmitted."
            + probe.diagnostic_suffix(),
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
