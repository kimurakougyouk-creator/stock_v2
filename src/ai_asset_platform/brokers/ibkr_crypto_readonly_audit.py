"""Read-only IBKR Paper crypto availability audit.

This diagnostic intentionally sends no Order, no What-If order, and no market
order request. It only asks IBKR ContractDetails for an explicit diagnostic
instrument (BTC/USD) on each currently allowed crypto venue. A resolved
ContractDetails response proves catalog/API visibility only; it does NOT prove
that the account, residence, or Paper account has crypto trading permission.
"""
from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_crypto_contract import ALLOWED_CRYPTO_EXCHANGES
from ai_asset_platform.brokers.ibkr_crypto_discovery import discover_ibkr_paper_crypto


DIAGNOSTIC_SYMBOL = "BTC"
DIAGNOSTIC_CURRENCY = "USD"


@dataclass(frozen=True)
class CryptoVenueAudit:
    exchange: str
    connected: bool
    resolved: bool
    endpoint_port: int | None
    candidate_count: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class CryptoReadonlyAuditResult:
    venues: tuple[CryptoVenueAudit, ...]
    api_catalog_visible: bool
    account_permission_proven: bool = False
    paper_trading_proven: bool = False
    real_order_sent: bool = False
    live_order_sent: bool = False


def run_crypto_readonly_audit() -> CryptoReadonlyAuditResult:
    rows: list[CryptoVenueAudit] = []
    for exchange in sorted(ALLOWED_CRYPTO_EXCHANGES):
        result = discover_ibkr_paper_crypto(
            symbol=DIAGNOSTIC_SYMBOL,
            exchange=exchange,
            currency=DIAGNOSTIC_CURRENCY,
        )
        rows.append(
            CryptoVenueAudit(
                exchange=exchange,
                connected=result.connected,
                resolved=result.resolved,
                endpoint_port=result.endpoint_port,
                candidate_count=len(result.candidates),
                errors=result.errors,
            )
        )
    return CryptoReadonlyAuditResult(
        venues=tuple(rows),
        api_catalog_visible=any(row.resolved for row in rows),
    )


def main() -> int:
    result = run_crypto_readonly_audit()
    print("===== IBKR PAPER CRYPTO READ-ONLY AVAILABILITY AUDIT =====")
    print("DIAGNOSTIC TARGET       : BTC/USD")
    for row in result.venues:
        print(f"{row.exchange} CONNECTED       :", row.connected)
        print(f"{row.exchange} RESOLVED        :", row.resolved)
        print(f"{row.exchange} ENDPOINT PORT   :", row.endpoint_port)
        print(f"{row.exchange} CANDIDATE COUNT :", row.candidate_count)
        print(f"{row.exchange} ERRORS          :", list(row.errors))
    print("API CATALOG VISIBLE     :", result.api_catalog_visible)
    print("ACCOUNT PERMISSION PROVEN:", result.account_permission_proven)
    print("PAPER TRADING PROVEN    :", result.paper_trading_proven)
    print("REAL ORDER SENT         :", result.real_order_sent)
    print("LIVE ORDER SENT         :", result.live_order_sent)
    # A read-only diagnostic itself succeeds even when no crypto catalog entry
    # is visible; that outcome is evidence and must not be converted into an
    # inferred trading capability.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
