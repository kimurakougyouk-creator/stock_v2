from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.core.asset_classes import AssetClass


@dataclass(frozen=True)
class InstrumentSpec:
    """Broker-neutral description of a tradable instrument.

    Paper transmission fails closed unless a broker-audited test quantity is
    supplied explicitly.  This prevents a stock/ETF pilot assumption from
    leaking into markets with different lot-size rules.
    """

    symbol: str
    asset_class: AssetClass
    exchange: str = "SMART"
    currency: str = "USD"
    expiry: str | None = None
    strike: float | None = None
    right: str | None = None
    multiplier: str | None = None
    verified_paper_test_quantity: int | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if not self.exchange.strip():
            raise ValueError("exchange must not be empty")
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
        if self.verified_paper_test_quantity is not None and self.verified_paper_test_quantity <= 0:
            raise ValueError("verified_paper_test_quantity must be positive when provided")
        if self.asset_class is AssetClass.FUTURE and not self.expiry:
            raise ValueError("future requires expiry")
        if self.asset_class is AssetClass.OPTION:
            if not self.expiry:
                raise ValueError("option requires expiry")
            if self.strike is None or self.strike <= 0:
                raise ValueError("option requires a positive strike")
            if (self.right or "").upper() not in {"C", "P"}:
                raise ValueError("option right must be C or P")
