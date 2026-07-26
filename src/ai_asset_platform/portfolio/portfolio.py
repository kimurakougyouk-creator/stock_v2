from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.portfolio.position import Position


class Portfolio:
    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self._realized_pnl = 0.0

    def add_position(self, position: Position) -> None:
        self._positions[position.symbol] = position

    def get_position(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def get_all_positions(self) -> list[Position]:
        return list(self._positions.values())

    @property
    def total_cost(self) -> float:
        return sum(position.cost for position in self._positions.values())

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    def apply_fill(self, fill: FillResult) -> None:
        current = self.get_position(fill.symbol)

        if fill.side is OrderSide.SELL:
            if current is None:
                raise ValueError("売却できる保有株がありません")

            if fill.quantity > current.quantity:
                raise ValueError("保有数量を超えて売却できません")

            profit = (
                fill.fill_price - current.average_price
            ) * fill.quantity
            self._realized_pnl += profit

            remaining = current.quantity - fill.quantity

            if remaining == 0:
                del self._positions[fill.symbol]
            else:
                self._positions[fill.symbol] = Position(
                    symbol=current.symbol,
                    quantity=remaining,
                    average_price=current.average_price,
                )
            return

        if current is None:
            self._positions[fill.symbol] = Position(
                symbol=fill.symbol,
                quantity=fill.quantity,
                average_price=fill.fill_price,
            )
            return

        new_quantity = current.quantity + fill.quantity
        new_total_cost = current.cost + fill.amount
        new_average_price = new_total_cost / new_quantity

        self._positions[fill.symbol] = Position(
            symbol=fill.symbol,
            quantity=new_quantity,
            average_price=new_average_price,
        )
