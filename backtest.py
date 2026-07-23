import math

from config import INITIAL_CAPITAL

DEFAULT_COMMISSION_RATE = 0.001
DEFAULT_SLIPPAGE_RATE = 0.001


def run_backtest(
    df,
    atr_multiplier=2.5,
    show_log=False,
    initial_capital=INITIAL_CAPITAL,
    commission_rate=DEFAULT_COMMISSION_RATE,
    slippage_rate=DEFAULT_SLIPPAGE_RATE,
):
    """バックテスト実行"""

    position = False
    buy_price = 0.0
    highest_price = 0.0
    stop_price = 0.0
    buy_date = None
    shares = 0.0
    buy_commission = 0.0
    gross_cost = 0.0

    trades = []
    asset_curve = []

    capital = initial_capital
    max_drawdown = 0.0
    peak_equity = initial_capital

    for i in range(len(df)):
        date = df.index[i]
        price = df["Close"].iloc[i]
        atr = df["ATR"].iloc[i]
        buy_signal = bool(df["Buy"].iloc[i])

        if not _is_valid_number(price):
            continue

        # 買い
        if (not position) and buy_signal and _is_valid_number(atr):
            buy_price = price * (1 + slippage_rate)
            buy_commission = capital * commission_rate
            available_capital = capital - buy_commission

            if available_capital <= 0 or buy_price <= 0:
                asset_curve.append(_asset_snapshot(date, capital, peak_equity))
                continue

            position = True
            buy_date = date
            shares = available_capital / buy_price
            gross_cost = shares * buy_price
            highest_price = buy_price
            stop_price = buy_price - atr * atr_multiplier

            if show_log:
                print(f"買い : {buy_date.date()}  {buy_price:.2f}")

        # 保有中
        elif position:
            highest_price = max(highest_price, price)

            if price >= buy_price * 1.05:
                stop_price = max(stop_price, buy_price)

            if _is_valid_number(atr):
                atr_stop = highest_price - atr * atr_multiplier
                stop_price = max(stop_price, atr_stop)

            sell_signal = price <= stop_price

            if sell_signal:
                sell_price = price * (1 - slippage_rate)
                sell_date = date
                capital, trade = _close_position(
                    previous_capital=capital,
                    buy_date=buy_date,
                    sell_date=sell_date,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    shares=shares,
                    buy_commission=buy_commission,
                    gross_cost=gross_cost,
                    commission_rate=commission_rate,
                )
                trades.append(trade)
                position = False
                shares = 0.0

                if show_log:
                    print(
                        f"売り : {sell_date.date()}  "
                        f"{sell_price:.2f}  "
                        f"{trade['profit']:.2f}%"
                    )

        equity = _calculate_equity(capital, shares, price, position, slippage_rate, commission_rate)
        peak_equity = max(peak_equity, equity)
        asset_curve.append(_asset_snapshot(date, equity, peak_equity))

    if position:
        sell_price = df["Close"].iloc[-1] * (1 - slippage_rate)
        sell_date = df.index[-1]
        capital, trade = _close_position(
            previous_capital=capital,
            buy_date=buy_date,
            sell_date=sell_date,
            buy_price=buy_price,
            sell_price=sell_price,
            shares=shares,
            buy_commission=buy_commission,
            gross_cost=gross_cost,
            commission_rate=commission_rate,
        )
        trades.append(trade)

        equity = capital
        if asset_curve and asset_curve[-1]["date"] == sell_date:
            peak_equity = max(peak_equity, equity)
            asset_curve[-1] = _asset_snapshot(sell_date, equity, peak_equity)
        else:
            peak_equity = max(peak_equity, equity)
            asset_curve.append(_asset_snapshot(sell_date, equity, peak_equity))

    for value in asset_curve:
        max_drawdown = max(max_drawdown, value["drawdown"])

    trade_count = len(trades)
    average_hold_days = sum(t["hold_days"] for t in trades) / trade_count if trade_count > 0 else 0
    win_count = sum(1 for t in trades if t["profit"] > 0)
    win_rate = win_count / trade_count * 100 if trade_count > 0 else 0.0
    final_capital = capital if not position else asset_curve[-1]["capital"] if asset_curve else initial_capital
    total_profit = (final_capital - initial_capital) / initial_capital * 100
    net_profit_yen = final_capital - initial_capital
    total_commission = sum(t["commission"] for t in trades)

    return {
        "trades": trades,
        "asset_curve": asset_curve,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "total_profit": total_profit,
        "final_capital": final_capital,
        "net_profit_yen": net_profit_yen,
        "total_commission": total_commission,
        "average_hold_days": average_hold_days,
        "max_drawdown": max_drawdown,
    }


def _close_position(
    previous_capital,
    buy_date,
    sell_date,
    buy_price,
    sell_price,
    shares,
    buy_commission,
    gross_cost,
    commission_rate,
):
    gross_proceeds = shares * sell_price
    sell_commission = gross_proceeds * commission_rate
    commission = buy_commission + sell_commission
    next_capital = gross_proceeds - sell_commission
    gross_profit_yen = gross_proceeds - gross_cost
    net_profit_yen = next_capital - previous_capital
    gross_profit = gross_profit_yen / gross_cost * 100 if gross_cost else 0.0
    profit = net_profit_yen / previous_capital * 100 if previous_capital else 0.0
    hold_days = (sell_date - buy_date).days

    return next_capital, {
        "buy_date": buy_date,
        "sell_date": sell_date,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "shares": shares,
        "profit": profit,
        "gross_profit": gross_profit,
        "gross_profit_yen": gross_profit_yen,
        "net_profit_yen": net_profit_yen,
        "commission": commission,
        "capital": next_capital,
        "hold_days": hold_days,
    }


def _calculate_equity(capital, shares, price, position, slippage_rate, commission_rate):
    if not position:
        return capital

    liquidation_price = price * (1 - slippage_rate)
    gross_value = shares * liquidation_price
    sell_commission = gross_value * commission_rate
    return gross_value - sell_commission


def _asset_snapshot(date, capital, peak_equity):
    drawdown = (peak_equity - capital) / peak_equity * 100 if peak_equity else 0.0
    return {
        "date": date,
        "capital": capital,
        "drawdown": drawdown,
    }


def _is_valid_number(value):
    try:
        return math.isfinite(value)
    except (TypeError, ValueError):
        return False
