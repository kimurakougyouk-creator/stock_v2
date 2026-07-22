import pandas as pd


def run_backtest(df, atr_multiplier=2.5, show_log=False):
    """
    バックテスト実行
    """

    position = False
    buy_price = 0.0
    highest_price = 0.0
    stop_price = 0.0

    buy_date = None

    trades = []

    for i in range(len(df)):

        price = df["Close"].iloc[i]

        # 買い
        if (not position) and df["Buy"].iloc[i]:

            position = True
            buy_price = price
            buy_date = df.index[i]

            highest_price = buy_price
            stop_price = buy_price - df["ATR"].iloc[i] * atr_multiplier

            if show_log:
                print(f"買い : {buy_date.date()}  {buy_price:.2f}")

           # print(f"買い : {buy_date.date()}  {buy_price:.2f}")

        # 保有中
        elif position:

            # 高値更新
            highest_price = max(highest_price, price)

            # 利益5%以上なら建値ストップ
            if price >= buy_price * 1.05:
                stop_price = max(stop_price, buy_price)

            # ATRトレーリングストップ
            atr_stop = highest_price - df["ATR"].iloc[i] * atr_multiplier
            stop_price = max(stop_price, atr_stop)

            # 売り条件
            sell_signal = (
                price <= stop_price
            )

            if sell_signal:

                sell_price = price
                sell_date = df.index[i]

                profit = (
                    (sell_price - buy_price)
                    / buy_price
                    * 100
                )

                hold_days = (sell_date - buy_date).days

                trades.append({
                    "buy_date": buy_date,
                    "sell_date": sell_date,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "profit": profit,
                    "hold_days": hold_days
                })

                if show_log:
                    print(
                        f"売り : {sell_date.date()}  "
                        f"{sell_price:.2f}  "
                        f"{profit:.2f}%"
                    )

                position = False

    trade_count = len(trades)

    if trade_count > 0:
        average_hold_days = sum(t["hold_days"] for t in trades) / trade_count
    else:
        average_hold_days = 0

    if trade_count > 0:
        win_count = sum(1 for t in trades if t["profit"] > 0)
        win_rate = win_count / trade_count * 100
        total_profit = sum(t["profit"] for t in trades)
    else:
        win_rate = 0.0
        total_profit = 0.0

    return {
        "trades": trades,
        "trade_count": trade_count,
        "win_rate": win_rate,
        "total_profit": total_profit,
        "average_hold_days": average_hold_days,
    }
