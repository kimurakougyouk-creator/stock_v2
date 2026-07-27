from ai_asset_platform.brokers.orders import FillResult, OrderSide
from ai_asset_platform.portfolio.portfolio import Portfolio


class Account:
    def __init__(self, initial_cash: float) -> None:
        if initial_cash < 0:
            raise ValueError("初期現金残高は0以上にしてください")

        self._cash = initial_cash
        self._portfolio = Portfolio()

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def buying_power(self) -> float:
        return self._cash

    @property
    def portfolio(self) -> Portfolio:
        return self._portfolio

    def apply_fill(self, fill: FillResult) -> None:
        if fill.side is OrderSide.BUY:
            if fill.amount > self._cash:
                raise ValueError("買付可能額が不足しています")

            self._portfolio.apply_fill(fill)
            self._cash -= fill.amount
            return

        if fill.side is OrderSide.SELL:
            self._portfolio.apply_fill(fill)
            self._cash += fill.amount
            return

        raise ValueError(f"未対応の注文種別です: {fill.side}")

    def get_summary(
        self,
        market_prices: dict[str, float],
    ) -> dict[str, float]:
        return self._portfolio.get_summary(
            cash=self._cash,
            market_prices=market_prices,
        )
