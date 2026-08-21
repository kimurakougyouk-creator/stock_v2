from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.core.asset_classes import AssetClass


@dataclass(frozen=True)
class InstrumentSpec:
    """Broker非依存の金融商品定義。

    対応を実証していない商品を推測で注文可能にしないため、
    商品固有情報はOrderRequestとは分離して保持する。
    """

    symbol: str
    asset_class: AssetClass
    exchange: str
    currency: str
    expiry: str | None = None
    strike: float | None = None
    right: str | None = None
    multiplier: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbolは空にできません。")
        if not self.exchange.strip():
            raise ValueError("exchangeは空にできません。")
        if not self.currency.strip():
            raise ValueError("currencyは空にできません。")

        if self.asset_class is AssetClass.FUTURE and not self.expiry:
            raise ValueError("先物にはexpiryが必要です。")

        if self.asset_class is AssetClass.OPTION:
            if not self.expiry:
                raise ValueError("オプションにはexpiryが必要です。")
            if self.strike is None or self.strike <= 0:
                raise ValueError("オプションには正のstrikeが必要です。")
            normalized_right = (self.right or "").upper()
            if normalized_right not in {"C", "P"}:
                raise ValueError("オプションrightはCまたはPです。")

        if self.asset_class not in {AssetClass.FUTURE, AssetClass.OPTION}:
            if any(value is not None for value in (self.expiry, self.strike, self.right, self.multiplier)):
                raise ValueError("この商品クラスにはデリバティブ固有情報を指定できません。")
