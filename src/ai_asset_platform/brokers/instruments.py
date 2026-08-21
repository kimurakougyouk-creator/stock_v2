from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.core.asset_classes import AssetClass


@dataclass(frozen=True)
class InstrumentSpec:
    """Broker-neutral description of a tradable instrument.

    This keeps IBKR-specific Contract fields out of strategy code.  Product
    specific requirements are validated here; broker support remains
    fail-closed in the contract factory until that asset class is explicitly
    implemented and tested.
    """

    symbol: str
    asset_class: AssetClass
    exchange: str = "SMART"
    currency: str = "USD"
    expiry: str | None = None
    strike: float | None = None
    right: str | None = None
    multiplier: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if not self.exchange.strip():
            raise ValueError("exchange must not be empty")
        if not self.currency.strip():
            raise ValueError("currency must not be empty")

        if self.asset_class is AssetClass.FUTURE and not self.expiry:
            raise ValueError("future requires expiry")

        if self.asset_class is AssetClass.OPTION:
            if not self.expiry:
                raise ValueError("option requires expiry")
            if self.strike is None or self.strike <= 0:
                raise ValueError("option requires a positive strike")
            if (self.right or "").upper() not in {"C", "P"}:
                raise ValueError("option right must be C or P")
