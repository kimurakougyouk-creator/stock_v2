from ai_asset_platform.portfolio.position import Position


class Portfolio:
    def __init__(self):
        self._positions = {}

    def add_position(self, position: Position):
        self._positions[position.symbol] = position

    def get_position(self, symbol: str):
        return self._positions.get(symbol)

    def get_all_positions(self):
        return list(self._positions.values())

    @property
    def total_cost(self):
        return sum(p.cost for p in self._positions.values())
