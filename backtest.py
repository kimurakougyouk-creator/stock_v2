import math

from config import INITIAL_CAPITAL

DEFAULT_COMMISSION_RATE = 0.001
DEFAULT_SLIPPAGE_RATE = 0.001
DEFAULT_TAKE_PROFIT_PCT = 0.10
DEFAULT_STOP_LOSS_PCT = 0.05
DEFAULT_MAX_LOSS_PCT = 0.01
DEFAULT_LOT_SIZE = 100


def run_backtest(
    df,
    atr_multiplier=2.5,
    show_log=False,
    initial_capital=INITIAL_CAPITAL,
    commission_rate=DEFAULT_COMMISSION_RATE,
    slippage_rate=DEFAULT_SLIPPAGE_RATE,
    take_profit_pct=DEFAULT_TAKE_PROFIT_PCT,
    stop_loss_pct=DEFAULT_STOP_LOSS_PCT,
    max_loss_pct=DEFAULT_MAX_LOSS_PCT,
    lot_size=DEFAULT_LOT_SIZE,
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
    cash_balance = 0.0
    risk_amount = 0.0
    capital_usage = 0.0

    trades = []
    asset_curve = []

    capital = initial_capital
    max_drawdown = 0.0
    peak_equity = initial_capital

    for i in range(len(df)):
        date = df.index[i]
        price = df["Close"].iloc[i]
        atr = df["ATR"].iloc[i]
        buy_signal = _is_true_signal(df["Buy"].iloc[i])

        if not _is_valid_number(price):
            continue

        # 買い
        if (not position) and buy_signal and _is_valid_number(atr):
            buy_price = price * (1 + slippage_rate)
            highest_price = buy_price
            stop_price = max(
                buy_price * (1 - stop_loss_pct),
                buy_price - atr * atr_multiplier,
            )
            shares, risk_amount, capital_usage = _calculate_position_size(
                capital=capital,
                buy_price=buy_price,
                stop_price=stop_price,
                commission_rate=commission_rate,
                max_loss_pct=max_loss_pct,
                lot_size=lot_size,
            )

            if shares < lot_size:
                asset_curve.append(_asset_snapshot(date, capital, peak_equity))
                continue

            position = True
            buy_date = date
            gross_cost = shares * buy_price
            buy_commission = gross_cost * commission_rate
            cash_balance = capital - gross_cost - buy_commission

            if show_log:
                print(f"買い : {buy_date.date()}  {buy_price:.2f}")

        # 保有中
        elif position:
            highest_price = max(highest_price, price)

            fixed_stop = buy_price * (1 - stop_loss_pct)
            stop_price = max(stop_price, fixed_stop)

            if price >= buy_price * 1.05:
                stop_price = max(stop_price, buy_price)

            if _is_valid_number(atr):
                atr_stop = highest_price - atr * atr_multiplier
                stop_price = max(stop_price, atr_stop)

            take_profit_price = buy_price * (1 + take_profit_pct)
            exit_reason = _get_exit_reason(price, take_profit_price, stop_price, fixed_stop)

            if exit_reason:
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
                    cash_balance=cash_balance,
                    risk_amount=risk_amount,
                    capital_usage=capital_usage,
                    commission_rate=commission_rate,
                    exit_reason=exit_reason,
                )
                trades.append(trade)
                position = False
                shares = 0.0
                cash_balance = 0.0
                risk_amount = 0.0
                capital_usage = 0.0

                if show_log:
                    print(
                        f"売り : {sell_date.date()}  "
                        f"{sell_price:.2f}  "
                        f"{trade['profit']:.2f}%"
                    )

        equity = _calculate_equity(capital, shares, price, position, slippage_rate, commission_rate, cash_balance)
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
            cash_balance=cash_balance,
            risk_amount=risk_amount,
            capital_usage=capital_usage,
            commission_rate=commission_rate,
            exit_reason="end_of_data",
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
    cash_balance,
    risk_amount,
    capital_usage,
    commission_rate,
    exit_reason,
):
    gross_proceeds = shares * sell_price
    sell_commission = gross_proceeds * commission_rate
    commission = buy_commission + sell_commission
    next_capital = cash_balance + gross_proceeds - sell_commission
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
        "risk_amount": risk_amount,
        "capital_usage": capital_usage,
        "exit_reason": exit_reason,
    }


def _calculate_position_size(capital, buy_price, stop_price, commission_rate, max_loss_pct, lot_size):
    risk_per_share = buy_price - stop_price

    if risk_per_share <= 0 or buy_price <= 0 or lot_size <= 0:
        return 0, 0.0, 0.0

    max_risk_amount = capital * max_loss_pct
    risk_limited_shares = int(max_risk_amount // risk_per_share)
    affordable_shares = int(capital // (buy_price * (1 + commission_rate)))
    shares = min(risk_limited_shares, affordable_shares)
    shares = shares // lot_size * lot_size

    if shares <= 0:
        return 0, 0.0, 0.0

    gross_cost = shares * buy_price
    buy_commission = gross_cost * commission_rate
    risk_amount = shares * risk_per_share
    capital_usage = (gross_cost + buy_commission) / capital * 100 if capital else 0.0

    return shares, risk_amount, capital_usage


def _get_exit_reason(price, take_profit_price, stop_price, fixed_stop):
    if price >= take_profit_price:
        return "take_profit"

    if price <= stop_price:
        if stop_price > fixed_stop:
            return "trailing_stop"
        return "stop_loss"

    return None


def _calculate_equity(capital, shares, price, position, slippage_rate, commission_rate, cash_balance=0.0):
    if not position:
        return capital

    liquidation_price = price * (1 - slippage_rate)
    gross_value = shares * liquidation_price
    sell_commission = gross_value * commission_rate
    return cash_balance + gross_value - sell_commission


def _asset_snapshot(date, capital, peak_equity):
    drawdown = (peak_equity - capital) / peak_equity * 100 if peak_equity else 0.0
    return {
        "date": date,
        "capital": capital,
        "drawdown": drawdown,
    }


def _is_true_signal(value):
    if value is True:
        return True

    if value is False or value is None:
        return False

    try:
        if not math.isfinite(value):
            return False
        return value != 0
    except (TypeError, ValueError):
        pass

    try:
        return bool(value)
    except (TypeError, ValueError):
        return False


def _is_valid_number(value):
    try:
        return math.isfinite(value)
    except (TypeError, ValueError):
        return False
