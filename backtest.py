from config import (
    INITIAL_CAPITAL,
    COMMISSION_RATE,
    SLIPPAGE_RATE,
    STOP_LOSS_RATE,
    TAKE_PROFIT_RATE,
)


def run_backtest(
    df,
    atr_multiplier=2.5,
    show_log=False,
    initial_capital=INITIAL_CAPITAL,
    commission_rate=COMMISSION_RATE,
    slippage_rate=SLIPPAGE_RATE,
    stop_loss_rate=STOP_LOSS_RATE,
    take_profit_rate=TAKE_PROFIT_RATE,
):
    """バックテスト実行"""

    position = False
    buy_price = 0.0
    highest_price = 0.0
    stop_price = 0.0
    buy_date = None
    buy_commission = 0.0

    trades = []
    asset_curve = [{"date": df.index[0] if len(df) > 0 else None, "capital": initial_capital}]

    capital = initial_capital
    max_drawdown = 0.0

    for i in range(len(df)):

        price = df["Close"].iloc[i]

        # 買い
        if (not position) and df["Buy"].iloc[i]:

            position = True
            buy_price = price * (1 + slippage_rate)
            buy_date = df.index[i]
            buy_commission = capital * commission_rate

            highest_price = buy_price
            stop_price = buy_price - df["ATR"].iloc[i] * atr_multiplier

            if show_log:
                print(f"買い : {buy_date.date()}  {buy_price:.2f}")

        # 保有中
        elif position:

            highest_price = max(highest_price, price)

            if price >= buy_price * 1.05:
                stop_price = max(stop_price, buy_price)

            atr_stop = highest_price - df["ATR"].iloc[i] * atr_multiplier
            stop_price = max(stop_price, atr_stop)

            if price <= buy_price * (1 - stop_loss_rate):
                exit_reason = "stop_loss"
            elif price >= buy_price * (1 + take_profit_rate):
                exit_reason = "take_profit"
            elif price <= stop_price:
                exit_reason = "atr_stop"
            else:
                exit_reason = None

            if exit_reason:
                sell_price = price * (1 - slippage_rate)
                sell_date = df.index[i]
                capital, trade = _close_position(
                    capital,
                    buy_date,
                    sell_date,
                    buy_price,
                    sell_price,
                    buy_commission,
                    commission_rate,
                )
                trade["exit_reason"] = exit_reason
                asset_curve.append({"date": sell_date, "capital": capital})
                trades.append(trade)

                if show_log:
                    print(
                        f"売り : {sell_date.date()}  "
                        f"{sell_price:.2f}  "
                        f"{trade['profit']:.2f}%"
                    )

                position = False

    if position:
        sell_price = df["Close"].iloc[-1] * (1 - slippage_rate)
        sell_date = df.index[-1]
        capital, trade = _close_position(
            capital,
            buy_date,
            sell_date,
            buy_price,
            sell_price,
            buy_commission,
            commission_rate,
        )
        trade["exit_reason"] = "final_close"
        asset_curve.append({"date": sell_date, "capital": capital})
        trades.append(trade)

    trade_count = len(trades)
    average_hold_days = sum(t["hold_days"] for t in trades) / trade_count if trade_count > 0 else 0
    win_count = sum(1 for t in trades if t["profit"] > 0)
    win_rate = win_count / trade_count * 100 if trade_count > 0 else 0.0
    final_capital = capital
    total_profit = (final_capital - initial_capital) / initial_capital * 100
    net_profit_yen = final_capital - initial_capital
    total_commission = sum(t["commission"] for t in trades)

    if asset_curve:
        highest = asset_curve[0]["capital"]
        for value in asset_curve:
            if value["capital"] > highest:
                highest = value["capital"]
            drawdown = (highest - value["capital"]) / highest * 100 if highest else 0
            max_drawdown = max(max_drawdown, drawdown)

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


def _close_position(capital, buy_date, sell_date, buy_price, sell_price, buy_commission, commission_rate):
    gross_profit_rate = (sell_price - buy_price) / buy_price
    sell_commission = capital * (1 + gross_profit_rate) * commission_rate
    commission = buy_commission + sell_commission
    next_capital = capital * (1 + gross_profit_rate) - commission
    profit = (next_capital - capital) / capital * 100
    hold_days = (sell_date - buy_date).days

    return next_capital, {
        "buy_date": buy_date,
        "sell_date": sell_date,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "profit": profit,
        "gross_profit": gross_profit_rate * 100,
        "commission": commission,
        "capital": next_capital,
        "hold_days": hold_days,
    }
