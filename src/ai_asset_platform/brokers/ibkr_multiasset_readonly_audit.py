"""Batch read-only ContractDetails audit for multiple IBKR Paper asset classes.

This module is intentionally non-trading. It only calls existing discovery
helpers that request ContractDetails and never create or transmit an Order.
Known explicit audit targets may be supplied by the caller; futures remain
opt-in so no product is silently assumed.
"""
from __future__ import annotations

from dataclasses import dataclass
import os

from ai_asset_platform.brokers.ibkr_future_discovery import (
    IbkrFutureDiscoveryResult,
    discover_ibkr_paper_futures,
)
from ai_asset_platform.brokers.ibkr_fx_discovery import (
    IbkrFxDiscoveryResult,
    discover_ibkr_paper_fx,
)
from ai_asset_platform.brokers.ibkr_global_stock_discovery import (
    IbkrGlobalStockDiscoveryResult,
    discover_ibkr_paper_global_stock,
)


@dataclass(frozen=True)
class MultiAssetReadonlyAuditResult:
    global_stock: IbkrGlobalStockDiscoveryResult
    fx: IbkrFxDiscoveryResult
    future: IbkrFutureDiscoveryResult | None

    @property
    def order_sent(self) -> bool:
        return bool(
            self.global_stock.order_sent
            or self.fx.order_sent
            or (self.future is not None and self.future.order_sent)
        )

    @property
    def core_resolved(self) -> bool:
        return bool(self.global_stock.resolved and self.fx.resolved and not self.order_sent)


def run_multiasset_readonly_audit(
    *,
    stock_symbol: str = "9432",
    stock_exchange: str = "TSEJ",
    stock_currency: str = "JPY",
    fx_base: str = "USD",
    fx_quote: str = "JPY",
    fx_exchange: str = "IDEALPRO",
    future_symbol: str | None = None,
    future_exchange: str | None = None,
    future_currency: str = "USD",
    timeout: float = 10.0,
) -> MultiAssetReadonlyAuditResult:
    """Run explicit read-only discoveries without transmitting any order."""
    stock = discover_ibkr_paper_global_stock(
        symbol=stock_symbol,
        exchange=stock_exchange,
        currency=stock_currency,
        timeout=timeout,
    )
    fx = discover_ibkr_paper_fx(
        base_currency=fx_base,
        quote_currency=fx_quote,
        exchange=fx_exchange,
        timeout=timeout,
    )

    future: IbkrFutureDiscoveryResult | None = None
    if future_symbol is not None or future_exchange is not None:
        if not future_symbol or not future_exchange:
            raise ValueError("future_symbol and future_exchange must be provided together")
        future = discover_ibkr_paper_futures(
            symbol=future_symbol,
            exchange=future_exchange,
            currency=future_currency,
            timeout=timeout,
        )

    return MultiAssetReadonlyAuditResult(stock, fx, future)


def main() -> int:
    future_symbol = os.getenv("IBKR_AUDIT_FUTURE_SYMBOL") or None
    future_exchange = os.getenv("IBKR_AUDIT_FUTURE_EXCHANGE") or None
    future_currency = os.getenv("IBKR_AUDIT_FUTURE_CURRENCY", "USD")
    result = run_multiasset_readonly_audit(
        future_symbol=future_symbol,
        future_exchange=future_exchange,
        future_currency=future_currency,
    )

    print("===== IBKR PAPER MULTI-ASSET READ-ONLY AUDIT =====")
    print("GLOBAL STOCK RESOLVED :", result.global_stock.resolved)
    print("GLOBAL STOCK TARGET   :", f"{result.global_stock.symbol}/{result.global_stock.exchange}/{result.global_stock.currency}")
    print("GLOBAL STOCK COUNT    :", len(result.global_stock.candidates))
    print("FX RESOLVED           :", result.fx.resolved)
    print("FX TARGET             :", f"{result.fx.base_currency}/{result.fx.quote_currency}@{result.fx.exchange}")
    print("FX COUNT              :", len(result.fx.candidates))
    print("FUTURE REQUESTED      :", result.future is not None)
    print("FUTURE RESOLVED       :", result.future.resolved if result.future is not None else None)
    print("FUTURE COUNT          :", len(result.future.candidates) if result.future is not None else 0)
    print("ORDER SENT            :", result.order_sent)
    print("CORE RESOLVED         :", result.core_resolved)
    return 0 if result.core_resolved and not result.order_sent else 2


if __name__ == "__main__":
    raise SystemExit(main())
