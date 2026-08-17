from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_config import (
    IbkrConnectionConfig,
    create_ibkr_paper_config,
)
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderStatus

REQUIRED_HOST = "127.0.0.1"
REQUIRED_PORT = 4002
REQUIRED_SYMBOL = "AAPL"
REQUIRED_SIDE = OrderSide.BUY
REQUIRED_QUANTITY = 1


@dataclass(frozen=True)
class IbkrFirstPaperTestResult:
    status: str
    sent: bool
    order_id: str | None
    message: str


def validate_first_paper_test_conditions(
    config: IbkrConnectionConfig,
    order: OrderRequest,
) -> IbkrFirstPaperTestResult | None:
    """
    初回IBKR Paper実機テスト専用の固定条件だけを検証する。

    条件を満たさない場合はBLOCKED系の結果を返す。
    すべて満たす場合はNoneを返す(=送信を継続してよい)。
    この関数自身は注文を一切送信しない。
    """
    if config.host != REQUIRED_HOST or config.port != REQUIRED_PORT:
        return IbkrFirstPaperTestResult(
            status="BLOCKED_WRONG_ENDPOINT",
            sent=False,
            order_id=None,
            message=(
                "初回Paperテストは"
                f"{REQUIRED_HOST}:{REQUIRED_PORT} (IB Gateway Paper) 固定です。"
            ),
        )

    if not config.paper_trading or config.allow_live_trading:
        return IbkrFirstPaperTestResult(
            status="BLOCKED_LIVE_CONFIG",
            sent=False,
            order_id=None,
            message=(
                "Paper専用設定ではないため停止しました。"
                "Live Tradingは許可されません。"
            ),
        )

    if order.symbol.strip().upper() != REQUIRED_SYMBOL:
        return IbkrFirstPaperTestResult(
            status="BLOCKED_SYMBOL",
            sent=False,
            order_id=None,
            message=f"初回Paperテストは銘柄{REQUIRED_SYMBOL}のみ許可します。",
        )

    if order.side is not REQUIRED_SIDE:
        return IbkrFirstPaperTestResult(
            status="BLOCKED_SIDE",
            sent=False,
            order_id=None,
            message="初回Paperテストは BUY のみ許可します。",
        )

    if order.quantity != REQUIRED_QUANTITY:
        return IbkrFirstPaperTestResult(
            status="BLOCKED_QUANTITY",
            sent=False,
            order_id=None,
            message="初回Paperテストは数量1のみ許可します。",
        )

    return None


class IbkrFirstPaperTestGateway:
    """
    初回IBKR Paper実機テスト専用の、最小・固定の安全な入口。

    既存の汎用IbkrBrokerAdapter/transmit_ibkr_paper_orderをそのまま再利用し、
    新しい発注ロジックは実装しない。このクラスが追加するのは、
    初回実機テストのためだけの固定・使い捨て制約のみ:

    - 接続先はIB Gateway Paper(127.0.0.1:4002)固定
    - 注文はAAPL/BUY/1株固定(呼び出し側は変更できない)
    - 初期状態では送信禁止(enable_transmission=False)
    - 明示的にenable_transmission=Trueにした場合だけplaceOrderへ進む可能性がある
    - このインスタンスの生涯でplaceOrderは最大1回だけ
    """

    def __init__(
        self,
        *,
        enable_transmission: bool = False,
        fill_state_path: str
        | Path = "data/ibkr_first_paper_test_fill_state.json",
    ) -> None:
        self._broker = IbkrBrokerAdapter(
            create_ibkr_paper_config(use_gateway=True),
            enable_paper_order_transmission=enable_transmission,
            fill_state_path=fill_state_path,
        )
        self._attempted = False

    @property
    def config(self) -> IbkrConnectionConfig:
        return self._broker.config

    def connect(self) -> bool:
        return self._broker.connect()

    def is_connected(self) -> bool:
        return self._broker.is_connected()

    def disconnect(self) -> None:
        self._broker.disconnect()

    def place_first_test_order(self) -> IbkrFirstPaperTestResult:
        """
        AAPL BUY 1株の初回Paperテスト注文を安全条件下でだけ送信する。

        1インスタンスにつき1回しか試行できない
        (2回目以降は接続状態に関わらず常にBLOCKED_ALREADY_ATTEMPTEDを返す)。
        """
        if self._attempted:
            return IbkrFirstPaperTestResult(
                status="BLOCKED_ALREADY_ATTEMPTED",
                sent=False,
                order_id=None,
                message=(
                    "このテスト入口では既に1回試行済みのため、"
                    "再送信をブロックしました。"
                ),
            )
        self._attempted = True

        order = OrderRequest(
            symbol=REQUIRED_SYMBOL,
            side=REQUIRED_SIDE,
            quantity=REQUIRED_QUANTITY,
        )

        blocked = validate_first_paper_test_conditions(
            self._broker.config,
            order,
        )
        if blocked is not None:
            return blocked

        result = self._broker.place_order(order)

        return IbkrFirstPaperTestResult(
            status=result.status.value,
            sent=result.status is OrderStatus.ACCEPTED,
            order_id=result.order_id,
            message=result.message,
        )

    def order_status_snapshot(self, order_id: int) -> float:
        """orderStatus由来の、指定order_idの処理済み累積約定数量を返す。"""
        return self._broker.processed_filled(order_id)


def main() -> None:
    """
    初回Paperテストの安全な入口を診断表示のみで実行する。

    enable_transmission=Falseで初期化するため、実行しても注文は送信されない。
    実送信するには、呼び出し側が明示的にenable_transmission=Trueを指定し、
    このmain()とは別に自分でplace_first_test_order()を呼ぶ必要がある。
    """
    gateway = IbkrFirstPaperTestGateway()

    print("===== IBKR FIRST PAPER TEST (SAFE ENTRY) =====")
    print(f"ENDPOINT   : {gateway.config.host}:{gateway.config.port}")
    print(f"PAPER      : {gateway.config.paper_trading}")
    print(f"LIVE ALLOW : {gateway.config.allow_live_trading}")
    print(f"SYMBOL     : {REQUIRED_SYMBOL}")
    print(f"SIDE       : {REQUIRED_SIDE.value}")
    print(f"QUANTITY   : {REQUIRED_QUANTITY}")
    print("TRANSMISSION: disabled (this entry point never sends by itself)")


if __name__ == "__main__":
    main()
