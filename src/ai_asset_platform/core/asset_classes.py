"""金融商品・市場の拡張性を表す共通モデル。

このモジュールは「対応済み」と「将来対応したい」を混同しないための土台。
実際の注文可否はBroker/API・口座権限・法規・商品別リスク検証後に個別に有効化する。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssetClass(str, Enum):
    STOCK = "STOCK"
    ETF = "ETF"
    FX = "FX"
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    CRYPTO = "CRYPTO"


@dataclass(frozen=True)
class MarketCapability:
    """1つの市場・商品クラスについての機能状態。"""

    market: str
    asset_class: AssetClass
    broker: str
    paper_supported: bool = False
    live_supported: bool = False

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("marketは空にできません。")
        if not self.broker.strip():
            raise ValueError("brokerは空にできません。")
        if self.live_supported and not self.paper_supported:
            raise ValueError("Live対応はPaper対応の検証後にのみ有効化できます。")


# ここには実証済みの能力だけを書く。
# AAPL (US stock) と SPY (US ETF) はIBKR Paper実Fillまで確認済み。
# Liveは未解禁。Overnightは別ゲートのため、通常US_ETFの検証と混同しない。
VERIFIED_CAPABILITIES: tuple[MarketCapability, ...] = (
    MarketCapability(
        market="US_STOCK",
        asset_class=AssetClass.STOCK,
        broker="IBKR",
        paper_supported=True,
        live_supported=False,
    ),
    MarketCapability(
        market="US_ETF",
        asset_class=AssetClass.ETF,
        broker="IBKR",
        paper_supported=True,
        live_supported=False,
    ),
)

# 最終的な拡張対象。ここにあることは「取引可能・実装済み」を意味しない。
TARGET_ASSET_CLASSES: tuple[AssetClass, ...] = tuple(AssetClass)


def is_verified_paper_capability(*, market: str, asset_class: AssetClass, broker: str) -> bool:
    """実証済みPaper能力かを厳密に返す。"""

    return any(
        item.market == market
        and item.asset_class is asset_class
        and item.broker == broker
        and item.paper_supported
        for item in VERIFIED_CAPABILITIES
    )
