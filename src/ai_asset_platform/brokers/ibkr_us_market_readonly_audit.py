from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_etf_audit import (
    IbkrEtfAuditResult,
    audit_ibkr_paper_etf,
)
from ai_asset_platform.brokers.ibkr_overnight_audit import (
    IbkrOvernightAuditResult,
    audit_ibkr_paper_overnight_contract,
)


@dataclass(frozen=True)
class IbkrUsMarketReadonlyAuditResult:
    etf: IbkrEtfAuditResult
    overnight: IbkrOvernightAuditResult

    @property
    def ready(self) -> bool:
        return (
            self.etf.connected
            and self.etf.contract_resolved
            and not self.etf.order_sent
            and self.overnight.connected
            and self.overnight.base_contract_resolved
            and self.overnight.overnight_contract_ready
            and not self.overnight.order_sent
        )


def run_ibkr_us_market_readonly_audit(
    symbol: str = "SPY",
    *,
    config: IbkrConnectionConfig | None = None,
    timeout: float = 8.0,
) -> IbkrUsMarketReadonlyAuditResult:
    """Run normal ETF and Overnight contract audits without placing any order."""
    cfg = config or IbkrConnectionConfig()
    cfg.validate()
    if not cfg.paper_trading or cfg.allow_live_trading:
        raise RuntimeError("US market audit requires Paper Trading with Live disabled.")

    etf = audit_ibkr_paper_etf(symbol, config=cfg, timeout=timeout)
    overnight = audit_ibkr_paper_overnight_contract(
        symbol, config=cfg, timeout=timeout
    )
    return IbkrUsMarketReadonlyAuditResult(etf=etf, overnight=overnight)


def main() -> int:
    result = run_ibkr_us_market_readonly_audit()
    print("===== IBKR US MARKET READ-ONLY AUDIT =====")
    print("ETF CONNECTED          :", result.etf.connected)
    print("ETF CONTRACT RESOLVED  :", result.etf.contract_resolved)
    print("ETF ORDER SENT         :", result.etf.order_sent)
    print("ETF MESSAGE            :", result.etf.message)
    print("OVERNIGHT CONNECTED    :", result.overnight.connected)
    print("OVERNIGHT BASE RESOLVED:", result.overnight.base_contract_resolved)
    print("OVERNIGHT READY        :", result.overnight.overnight_contract_ready)
    print("PRIMARY EXCHANGE       :", result.overnight.primary_exchange)
    print("DESTINATION            :", result.overnight.destination)
    print("OVERNIGHT ORDER SENT   :", result.overnight.order_sent)
    print("OVERNIGHT MESSAGE      :", result.overnight.message)
    print("OVERALL READY          :", result.ready)
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
