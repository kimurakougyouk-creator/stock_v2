"""Version 3.0の注文管理。

初期状態では実際の注文を送信せず、注文内容だけを安全に記録します。
"""

from datetime import date, datetime
from pathlib import Path
import json


ORDER_LOG_DIR = Path("results")
ORDER_LOG_PATH = ORDER_LOG_DIR / "paper_orders.jsonl"


def create_paper_order(
    ticker: str,
    signal: str,
    shares: int,
    reference_price: float,
) -> dict:
    """模擬注文を作成してファイルへ記録します。"""

    signal = str(signal).upper()

    if signal not in {"BUY", "SELL"}:
        raise ValueError("signalはBUYまたはSELLを指定してください。")

    if int(shares) <= 0:
        raise ValueError("sharesは1株以上を指定してください。")

    order = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "PAPER",
        "ticker": str(ticker),
        "side": signal,
        "shares": int(shares),
        "reference_price": float(reference_price),
        "status": "RECORDED",
    }

    ORDER_LOG_DIR.mkdir(parents=True, exist_ok=True)

    with ORDER_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(order, ensure_ascii=False) + "\n")

    return order


def load_paper_orders() -> list[dict]:
    """保存済みの模擬注文を読み込みます。"""

    if not ORDER_LOG_PATH.exists():
        return []

    orders = []

    with ORDER_LOG_PATH.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                orders.append(json.loads(line))

    return orders


def calculate_available_cash(initial_capital: float) -> float:
    """注文履歴を使って現在利用できる現金残高を計算します。

    BUY金額を差し引き、SELL金額を加算します。
    手数料や税金は現段階では計算に含めません。
    """

    try:
        available_cash = float(initial_capital)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "initial_capitalは0以上の数値を指定してください。"
        ) from exc

    if available_cash < 0:
        raise ValueError(
            "initial_capitalは0以上の数値を指定してください。"
        )

    for order in load_paper_orders():
        try:
            side = str(order["side"]).upper()
            shares = int(order["shares"])
            price = float(order["reference_price"])
        except (KeyError, TypeError, ValueError):
            continue

        if shares <= 0 or price < 0:
            continue

        order_amount = shares * price

        if side == "BUY":
            available_cash -= order_amount
        elif side == "SELL":
            available_cash += order_amount

    return max(0.0, available_cash)


def get_open_positions() -> dict[str, int]:
    """現在の保有株数を銘柄ごとに集計します。"""

    positions = {}

    for order in load_paper_orders():
        ticker = order["ticker"]
        shares = int(order["shares"])

        if order["side"] == "BUY":
            positions[ticker] = positions.get(ticker, 0) + shares
        elif order["side"] == "SELL":
            positions[ticker] = positions.get(ticker, 0) - shares

    return {ticker: shares for ticker, shares in positions.items() if shares != 0}



def calculate_daily_buy_order_count() -> int:
    """本日記録されたBUY注文数を返す。"""

    orders = load_paper_orders()
    if not orders:
        return 0

    today = datetime.now().date()
    count = 0

    for order in orders:
        if str(order.get("side", "")).upper() != "BUY":
            continue

        created_at = order.get("created_at")
        if not created_at:
            continue

        try:
            order_date = datetime.fromisoformat(
                str(created_at)
            ).date()
        except ValueError:
            continue

        if order_date == today:
            count += 1

    return count

def calculate_daily_realized_pnl(
    target_date: date | None = None,
) -> float:
    """指定日の売却で確定した損益を注文履歴から計算します。

    買付価格は銘柄ごとの移動平均取得価格を使用します。
    target_dateを省略した場合は今日の損益を返します。
    """

    if target_date is None:
        target_date = date.today()

    positions: dict[str, int] = {}
    average_costs: dict[str, float] = {}
    daily_realized_pnl = 0.0

    for order in load_paper_orders():
        try:
            created_at = datetime.fromisoformat(str(order["created_at"]))
            ticker = str(order["ticker"])
            side = str(order["side"]).upper()
            shares = int(order["shares"])
            price = float(order["reference_price"])
        except (KeyError, TypeError, ValueError):
            continue

        if shares <= 0:
            continue

        held_shares = positions.get(ticker, 0)
        average_cost = average_costs.get(ticker, 0.0)

        if side == "BUY":
            total_cost = (held_shares * average_cost) + (shares * price)
            new_shares = held_shares + shares

            positions[ticker] = new_shares
            average_costs[ticker] = (
                total_cost / new_shares
                if new_shares > 0
                else 0.0
            )

        elif side == "SELL" and held_shares > 0:
            sold_shares = min(shares, held_shares)
            trade_pnl = (price - average_cost) * sold_shares

            if created_at.date() == target_date:
                daily_realized_pnl += trade_pnl

            remaining_shares = held_shares - sold_shares
            positions[ticker] = remaining_shares

            if remaining_shares <= 0:
                average_costs[ticker] = 0.0

    return daily_realized_pnl


def calculate_consecutive_losses() -> int:
    """直近の確定取引が何回連続で損失になったかを返します。

    SELLごとの確定損益を移動平均取得価格で計算します。
    利益または損益ゼロの取引があると連敗はリセットされます。
    """

    positions: dict[str, int] = {}
    average_costs: dict[str, float] = {}
    realized_trade_pnls: list[float] = []

    for order in load_paper_orders():
        try:
            ticker = str(order["ticker"])
            side = str(order["side"]).upper()
            shares = int(order["shares"])
            price = float(order["reference_price"])
        except (KeyError, TypeError, ValueError):
            continue

        if shares <= 0:
            continue

        held_shares = positions.get(ticker, 0)
        average_cost = average_costs.get(ticker, 0.0)

        if side == "BUY":
            total_cost = (held_shares * average_cost) + (shares * price)
            new_shares = held_shares + shares

            positions[ticker] = new_shares
            average_costs[ticker] = (
                total_cost / new_shares
                if new_shares > 0
                else 0.0
            )

        elif side == "SELL" and held_shares > 0:
            sold_shares = min(shares, held_shares)
            trade_pnl = (price - average_cost) * sold_shares
            realized_trade_pnls.append(trade_pnl)

            remaining_shares = held_shares - sold_shares
            positions[ticker] = remaining_shares

            if remaining_shares <= 0:
                average_costs[ticker] = 0.0

    consecutive_losses = 0

    for trade_pnl in reversed(realized_trade_pnls):
        if trade_pnl < 0:
            consecutive_losses += 1
        else:
            break

    return consecutive_losses


def calculate_unrealized_pnl(current_prices: dict[str, float]) -> dict[str, float]:
    """現在価格から保有銘柄の含み損益を計算します。"""

    pnl = {}

    for order in load_paper_orders():
        if order["side"] != "BUY":
            continue

        ticker = order["ticker"]

        if ticker not in current_prices:
            continue

        buy_price = float(order["reference_price"])
        current_price = float(current_prices[ticker])
        shares = int(order["shares"])

        pnl[ticker] = (current_price - buy_price) * shares

    return pnl


def calculate_portfolio_value(current_prices: dict[str, float]) -> float:
    """現在の保有資産評価額を計算します。"""

    total = 0.0

    positions = get_open_positions()

    for ticker, shares in positions.items():
        if ticker not in current_prices:
            continue

        total += current_prices[ticker] * shares

    return total


def generate_portfolio_report(current_prices: dict[str, float]) -> str:
    """資産状況レポートを作成します。"""

    value = calculate_portfolio_value(current_prices)
    pnl = calculate_unrealized_pnl(current_prices)

    lines = []
    lines.append(f"日時: {datetime.now():%Y-%m-%d %H:%M:%S}")
    lines.append(f"資産評価額: {value:,.0f}円")

    if pnl:
        lines.append("含み損益:")
        for ticker, profit in pnl.items():
            lines.append(f"  {ticker}: {profit:,.0f}円")

    return "\n".join(lines)


def save_portfolio_report(current_prices: dict[str, float], filename: str = "portfolio_report.txt") -> None:
    """資産レポートをテキストファイルへ保存します。"""

    report = generate_portfolio_report(current_prices)

    with open(filename, "a+", encoding="utf-8") as f:
        f.seek(0, 2)
        file_size = f.tell()

        if file_size > 0:
            f.seek(file_size - 1)
            if f.read(1) != "\n":
                f.write("\n")

        f.write(report)
        f.write("\n" + "=" * 40 + "\n")

def generate_order_list():
    """保存されているペーパー注文を見やすい一覧にする。"""
    orders = load_paper_orders()

    lines = ["===== 注文一覧 ====="]

    if not orders:
        lines.append("注文はありません")
        return "\n".join(lines)

    for i, order in enumerate(orders, 1):
        lines.append(
            f"{i}. {order['ticker']} "
            f"{order['side']} "
            f"{order['shares']}株 "
            f"@ {order['reference_price']:,.0f}円 "
            f"({order['status']})"
        )

    return "\n".join(lines)
