from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.core.asset_classes import AssetClass


@dataclass(frozen=True)
class IbkrContractSpec:
    """Small testable representation of the IBKR Contract fields we set."""

    symbol: str
    sec_type: str
    exchange: str
    currency: str
    primary_exchange: str | None = None
    last_trade_date_or_contract_month: str | None = None
    strike: float | None = None
    right: str | None = None
    multiplier: str | None = None


_SEC_TYPES = {
    AssetClass.STOCK: "STK",
    AssetClass.ETF: "STK",
}


def build_ibkr_contract_spec(instrument: InstrumentSpec) -> IbkrContractSpec:
    """Translate a broker-neutral instrument to IBKR fields, fail closed.

    Only STOCK and ETF are intentionally enabled in this first foundation.
    FX/FUTURE/OPTION/CRYPTO remain rejected until their product-specific
    semantics and Paper E2E tests are implemented under issue #56.
    """

    sec_type = _SEC_TYPES.get(instrument.asset_class)
    if sec_type is None:
        raise ValueError(
            f"IBKR contract mapping is not verified for {instrument.asset_class.value}"
        )

    return IbkrContractSpec(
        symbol=instrument.symbol.strip(),
        sec_type=sec_type,
        exchange=instrument.exchange.strip().upper(),
        currency=instrument.currency.strip().upper(),
        primary_exchange=(
            instrument.primary_exchange.strip().upper()
            if instrument.primary_exchange is not None
            else None
        ),
    )


def to_ibapi_contract(spec: IbkrContractSpec):
    """Create an ibapi Contract lazily so pure mapping tests need no connection."""

    try:
        from ibapi.contract import Contract
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError("ibapi is required to create an IBKR Contract") from exc

    contract = Contract()
    contract.symbol = spec.symbol
    contract.secType = spec.sec_type
    contract.exchange = spec.exchange
    contract.currency = spec.currency
    if spec.primary_exchange:
        contract.primaryExchange = spec.primary_exchange
    if spec.last_trade_date_or_contract_month:
        contract.lastTradeDateOrContractMonth = spec.last_trade_date_or_contract_month
    if spec.strike is not None:
        contract.strike = spec.strike
    if spec.right:
        contract.right = spec.right
    if spec.multiplier:
        contract.multiplier = spec.multiplier
    return contract
