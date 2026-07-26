"""
注文データの共通形式
"""

from dataclasses import dataclass
from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("銘柄コードは必須です")

        if self.quantity <= 0:
            raise ValueError("注文数量は1以上にしてください")

        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None or self.limit_price <= 0:
                raise ValueError("指値注文には正しい価格が必要です")

        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("成行注文に指値価格は指定できません")


class OrderStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: OrderStatus
    message: str = ""

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise ValueError("注文IDは必須です")

    @property
    def is_accepted(self) -> bool:
        return self.status is OrderStatus.ACCEPTED


@dataclass(frozen=True)
class OrderRecord:
    request: OrderRequest
    result: OrderResult


@dataclass(frozen=True)
class FillResult:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    fill_price: float

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise ValueError("注文IDは必須です")

        if not self.symbol.strip():
            raise ValueError("銘柄コードは必須です")

        if self.quantity <= 0:
            raise ValueError("約定数量は1以上にしてください")

        if self.fill_price <= 0:
            raise ValueError("約定価格は0より大きくしてください")

    @property
    def amount(self) -> float:
        return self.quantity * self.fill_price
