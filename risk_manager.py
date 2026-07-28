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
