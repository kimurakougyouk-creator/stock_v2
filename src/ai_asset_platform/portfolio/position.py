from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    average_price: float

    def __post_init__(self):
        if not self.symbol.strip():
            raise ValueError("銘柄コードは必須です")
        if self.quantity <= 0:
            raise ValueError("数量は1以上である必要があります")
        if self.average_price <= 0:
            raise ValueError("平均取得価格は0より大きい必要があります")

    @property
    def cost(self) -> float:
        return self.quantity * self.average_price
