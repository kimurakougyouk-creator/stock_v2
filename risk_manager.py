"""自動売買のリスク管理計算。"""


def calculate_position_size(
    *,
    trading_capital: float,
    risk_per_trade_rate: float,
    entry_price: float,
    stop_loss_rate: float,
    lot_size: int = 100,
) -> int:
    """1回の取引で許容する損失額から注文株数を計算する。

    例:
        運用資金100万円、許容損失率1%、損切り率3%、
        株価1,000円の場合は300株を返す。

        許容損失額: 10,000円
        1株の想定損失: 30円
        10,000 ÷ 30 = 333株
        100株単位へ切り下げ = 300株
    """

    try:
        trading_capital = float(trading_capital)
        risk_per_trade_rate = float(risk_per_trade_rate)
        entry_price = float(entry_price)
        stop_loss_rate = float(stop_loss_rate)
        lot_size = int(lot_size)
    except (TypeError, ValueError):
        return 0

    if (
        trading_capital <= 0
        or risk_per_trade_rate <= 0
        or risk_per_trade_rate > 1
        or entry_price <= 0
        or stop_loss_rate <= 0
        or stop_loss_rate > 1
        or lot_size <= 0
    ):
        return 0

    permitted_loss_yen = trading_capital * risk_per_trade_rate
    loss_per_share_yen = entry_price * stop_loss_rate

    raw_shares = int(permitted_loss_yen // loss_per_share_yen)
    position_shares = (raw_shares // lot_size) * lot_size

    return max(0, position_shares)


def calculate_open_position_risk(
    orders: list[dict],
    *,
    stop_loss_rate: float,
) -> float:
    """保有中の全ポジションの想定損失額を合計する。

    BUY注文は平均取得価格へ加算し、SELL注文は保有株数から減算する。
    想定損失額は「平均取得価格 × 保有株数 × 損切り率」で計算する。
    """

    try:
        stop_loss_rate = float(stop_loss_rate)
    except (TypeError, ValueError):
        return 0.0

    if stop_loss_rate <= 0 or stop_loss_rate > 1:
        return 0.0

    positions: dict[str, int] = {}
    average_costs: dict[str, float] = {}

    for order in orders:
        try:
            ticker = str(order["ticker"])
            side = str(order["side"]).upper()
            shares = int(order["shares"])
            price = float(order["reference_price"])
        except (KeyError, TypeError, ValueError):
            continue

        if shares <= 0 or price <= 0:
            continue

        held_shares = positions.get(ticker, 0)
        average_cost = average_costs.get(ticker, 0.0)

        if side == "BUY":
            total_cost = (
                held_shares * average_cost
                + shares * price
            )
            new_shares = held_shares + shares

            positions[ticker] = new_shares
            average_costs[ticker] = total_cost / new_shares

        elif side == "SELL" and held_shares > 0:
            sold_shares = min(shares, held_shares)
            remaining_shares = held_shares - sold_shares
            positions[ticker] = remaining_shares

            if remaining_shares <= 0:
                average_costs[ticker] = 0.0

    total_risk_yen = 0.0

    for ticker, shares in positions.items():
        if shares <= 0:
            continue

        total_risk_yen += (
            average_costs.get(ticker, 0.0)
            * shares
            * stop_loss_rate
        )

    return max(0.0, total_risk_yen)

