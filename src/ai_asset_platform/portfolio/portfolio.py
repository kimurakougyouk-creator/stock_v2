from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.portfolio.position import Position


class Portfolio:
    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self._realized_pnl = 0.0
        self._realized_trade_pnls: list[float] = []

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

    @property
    def realized_trade_pnls(self) -> list[float]:
        """売却約定ごとの実現損益をコピーして返す。"""
        return self._realized_trade_pnls.copy()

    @staticmethod
    def _validate_cash(cash: float) -> None:
        if cash < 0:
            raise ValueError("現金残高は0以上にしてください")

    @staticmethod
    def _get_market_price(
        symbol: str,
        market_prices: dict[str, float],
    ) -> float:
        if symbol not in market_prices:
            raise ValueError(
                f"{symbol} の現在価格が指定されていません"
            )

        market_price = market_prices[symbol]

        if market_price <= 0:
            raise ValueError("現在価格は0より大きくしてください")

        return market_price

    def calculate_holdings_value(
        self,
        market_prices: dict[str, float],
    ) -> float:
        return sum(
            self._get_market_price(symbol, market_prices)
            * position.quantity
            for symbol, position in self._positions.items()
        )

    def calculate_total_assets(
        self,
        cash: float,
        market_prices: dict[str, float],
    ) -> float:
        self._validate_cash(cash)

        return cash + self.calculate_holdings_value(
            market_prices
        )

    def calculate_unrealized_pnl(
        self,
        market_prices: dict[str, float],
    ) -> float:
        return sum(
            (
                self._get_market_price(symbol, market_prices)
                - position.average_price
            )
            * position.quantity
            for symbol, position in self._positions.items()
        )

    def apply_fill(self, fill: FillResult) -> None:
        if fill.side is OrderSide.BUY:
            self._apply_buy_fill(fill)
            return

        if fill.side is OrderSide.SELL:
            self._apply_sell_fill(fill)
            return

        raise ValueError(f"未対応の注文種別です: {fill.side}")

    def _apply_buy_fill(self, fill: FillResult) -> None:
        current = self.get_position(fill.symbol)

        if current is None:
            self._positions[fill.symbol] = Position(
                symbol=fill.symbol,
                quantity=fill.quantity,
                average_price=fill.fill_price,
            )
            return

        new_quantity = current.quantity + fill.quantity
        new_total_cost = current.cost + fill.amount

        self._positions[fill.symbol] = Position(
            symbol=fill.symbol,
            quantity=new_quantity,
            average_price=new_total_cost / new_quantity,
        )

    def _apply_sell_fill(self, fill: FillResult) -> None:
        current = self.get_position(fill.symbol)

        if current is None:
            raise ValueError("売却できる保有株がありません")

        if fill.quantity > current.quantity:
            raise ValueError("保有数量を超えて売却できません")

        trade_pnl = (
            fill.fill_price - current.average_price
        ) * fill.quantity

        self._realized_pnl += trade_pnl
        self._realized_trade_pnls.append(trade_pnl)

        remaining_quantity = current.quantity - fill.quantity

        if remaining_quantity == 0:
            del self._positions[fill.symbol]
            return

        self._positions[fill.symbol] = Position(
            symbol=current.symbol,
            quantity=remaining_quantity,
            average_price=current.average_price,
        )

    def get_summary(
        self,
        cash: float,
        market_prices: dict[str, float],
    ) -> dict[str, float]:
        self._validate_cash(cash)

        holdings_value = self.calculate_holdings_value(
            market_prices
        )

        return {
            "cash": cash,
            "holdings": holdings_value,
            "total_assets": cash + holdings_value,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.calculate_unrealized_pnl(
                market_prices
            ),
        }
