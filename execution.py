import json
import math
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from logging import Logger
from datetime import datetime
from pathlib import Path
from typing import Any

from stability import create_daily_logger, safe_execute


@dataclass(frozen=True)
class Order:
    ticker: str
    side: str
    quantity: int
    price: float
    created_at: str
    reason: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (
            self.ticker,
            self.side,
            _date_key(self.created_at),
        )


class BrokerInterface(ABC):
    """証券会社ごとの接続処理を追加するための抽象インターフェース"""

    @abstractmethod
    def submit_order(self, order: Order, available_cash: float) -> bool:
        raise NotImplementedError


class BrokerClient(BrokerInterface):
    """既存コード互換のための別名基底クラス"""


class BrokerFactory:
    """設定に応じて利用するブローカーを作成するFactory"""

    @staticmethod
    def create(mode: str = "dry_run", **kwargs: Any) -> BrokerInterface:
        normalized_mode = (mode or "dry_run").lower()

        if normalized_mode in {"dry_run", "dry-run", "paper"}:
            return DryRunBroker(**kwargs)

        if normalized_mode in {"sbi", "sbi_sec", "sbi_securities", "live", "real"}:
            raise NotImplementedError(
                "実注文モードは未実装です。安全のため処理を停止しました。"
            )

        raise ValueError(f"unknown broker mode: {mode}")


class DryRunBroker(BrokerClient):
    """実注文を出さず、模擬注文だけをJSONに保存するブローカー"""

    def __init__(self, order_file: str | Path = "results/dry_run_orders.json", log_file: str | Path | None = None) -> None:
        self.order_file = Path(order_file)
        self.log_file = Path(log_file) if log_file else None
        self.order_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger = _create_logger(self.log_file)

    def submit_order(self, order: Order, available_cash: float) -> bool:
        def operation():
            validate_order(order, available_cash)
            orders = self._load_orders()

            if any(_order_key(saved) == order.key for saved in orders):
                self.logger.info("duplicate order skipped: %s", order)
                return False

            orders.append(asdict(order))
            self._save_orders(orders)
            self.logger.info("dry-run order recorded: %s", order)
            return True

        return safe_execute(operation, self.logger, default=False)

    def _load_orders(self) -> list[dict[str, Any]]:
        if not self.order_file.exists():
            return []

        with self.order_file.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save_orders(self, orders: list[dict[str, Any]]) -> None:
        with self.order_file.open("w", encoding="utf-8") as file:
            json.dump(orders, file, ensure_ascii=False, indent=2)


def record_dry_run_orders(
    ticker: str,
    backtest_result: Mapping[str, Any],
    broker: BrokerInterface,
    available_cash: float,
    dry_run: bool = True,
) -> list[Order]:
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


def create_order_from_signal(ticker: str, signal_row: Any, quantity: int, reason: str = "buy_signal") -> Order | None:
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


def validate_order(order: Order, available_cash: float) -> None:
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


def _is_buy_signal(signal_row: Any) -> bool:
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


def _format_datetime(value: Any) -> str:
    if value is None:
        return datetime.utcnow().isoformat()

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


def _order_key(order_dict: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        order_dict["ticker"],
        order_dict["side"],
        _date_key(order_dict["created_at"]),
    )


def _date_key(value: Any) -> str:
    return str(value).split("T", 1)[0].split(" ", 1)[0]


def _create_logger(log_file: str | Path | None) -> Logger:
    return create_daily_logger("dry_run_orders", log_dir="results", log_file=log_file)
