"""Version 3.0の注文管理。

初期状態では実際の注文を送信せず、注文内容だけを安全に記録します。
"""

from datetime import datetime
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
