import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Order:
    ticker: str
    side: str
    quantity: int
    price: float
    created_at: str
    reason: str

    @property
    def key(self):
        return (
            self.ticker,
            self.side,
            _date_key(self.created_at),
        )


class BrokerClient:
    """証券会社ごとの接続処理を追加するための基底クラス"""

    def submit_order(self, order, available_cash):
        raise NotImplementedError


class DryRunBroker(BrokerClient):
    """実注文を出さず、模擬注文だけをJSONに保存するブローカー"""

    def __init__(self, order_file="results/dry_run_orders.json", log_file="results/dry_run_orders.log"):
        self.order_file = Path(order_file)
        self.log_file = Path(log_file)
        self.order_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger = _create_logger(self.log_file)

    def submit_order(self, order, available_cash):
        try:
            validate_order(order, available_cash)
            orders = self._load_orders()

            if any(_order_key(saved) == order.key for saved in orders):
                self.logger.info("duplicate order skipped: %s", order)
                return False

            orders.append(asdict(order))
            self._save_orders(orders)
            self.logger.info("dry-run order recorded: %s", order)
            return True
        except Exception as exc:
            self.logger.exception("dry-run order failed: %s", exc)
            return False

    def _load_orders(self):
        if not self.order_file.exists():
            return []

        with self.order_file.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save_orders(self, orders):
        with self.order_file.open("w", encoding="utf-8") as file:
            json.dump(orders, file, ensure_ascii=False, indent=2)


def record_dry_run_orders(ticker, backtest_result, broker, available_cash, dry_run=True):
    """バックテスト結果からdry-runの買い/売り模擬注文を記録する"""

    if not dry_run:
        broker.logger.error("dry-run mode is disabled; real order execution is not implemented")
        return []

    recorded_orders = []

    for trade in backtest_result.get("trades", []):
        buy_order = Order(
            ticker=ticker,
            side="BUY",
            quantity=int(trade["shares"]),
            price=float(trade["buy_price"]),
            created_at=_format_datetime(trade["buy_date"]),
            reason="buy_signal",
        )

        if broker.submit_order(buy_order, available_cash):
            recorded_orders.append(buy_order)

        sell_order = Order(
            ticker=ticker,
            side="SELL",
            quantity=int(trade["shares"]),
            price=float(trade["sell_price"]),
            created_at=_format_datetime(trade["sell_date"]),
            reason=trade.get("exit_reason", "sell_signal"),
        )

        if broker.submit_order(sell_order, available_cash=0):
            recorded_orders.append(sell_order)

        available_cash = max(available_cash, trade.get("capital", available_cash))

    return recorded_orders


def create_order_from_signal(ticker, signal_row, quantity, reason="buy_signal"):
    """売買シグナル行から注文情報を作成する"""

    if not _is_buy_signal(signal_row):
        return None

    price = float(signal_row["Close"])
    created_at = _format_datetime(getattr(signal_row, "name", None))

    return Order(
        ticker=ticker,
        side="BUY",
        quantity=int(quantity),
        price=price,
        created_at=created_at,
        reason=reason,
    )


def validate_order(order, available_cash):
    if not order.ticker:
        raise ValueError("ticker is required")

    if order.side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")

    if order.quantity <= 0:
        raise ValueError("quantity must be greater than zero")

    if order.price <= 0:
        raise ValueError("price must be greater than zero")

    if order.side == "BUY" and order.quantity * order.price > available_cash:
        raise ValueError("order amount exceeds available cash")


def _is_buy_signal(signal_row):
    try:
        value = signal_row["Buy"]
    except (KeyError, TypeError, ValueError):
        return False

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


def _format_datetime(value):
    if value is None:
        return datetime.utcnow().isoformat()

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


def _order_key(order_dict):
    return (
        order_dict["ticker"],
        order_dict["side"],
        _date_key(order_dict["created_at"]),
    )


def _date_key(value):
    return str(value).split("T", 1)[0].split(" ", 1)[0]


def _create_logger(log_file):
    logger = logging.getLogger(f"dry_run_orders.{log_file}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)

    return logger
