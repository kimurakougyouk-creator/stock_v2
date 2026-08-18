from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from ai_asset_platform.brokers.ibkr import IbkrBrokerAdapter
from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderStatus

REQUIRED_HOST = "127.0.0.1"
REQUIRED_PORT = 4002
REQUIRED_SYMBOL = "AAPL"
REQUIRED_SIDE = OrderSide.BUY
REQUIRED_QUANTITY = 1

# 汎用システムが既定で使うclient_id=0とは別のIDを固定する。
# こうすることで、他のIBKR APIクライアント(汎用トレーディングシステム等)が
# 同時にclient_id=0で接続していても、初回Paperテスト専用の接続が
# 同一client_idの競合(接続拒否/強制切断)に巻き込まれない。
REQUIRED_CLIENT_ID = 501

# 送信直前に確認する、初回Paperテスト専用の固定Paper口座ID。
# 誤って別の口座(将来別のPaper/Live口座が同一client_id体系に
# 追加された場合等)へ送信することを防ぐための最終確認に使う。
REQUIRED_ACCOUNT_ID = "DUR570982"

DEFAULT_SEND_LOCK_PATH = "data/ibkr_first_paper_test_send.lock"

DEFAULT_ACCOUNT_VERIFICATION_TIMEOUT_SECONDS = 5.0


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

    - 接続先はIB Gateway Paper(127.0.0.1:4002)固定、client_idも専用に固定
    - 注文はAAPL/BUY/1株固定(呼び出し側は変更できない)
    - 初期状態では送信禁止(enable_transmission=False)
    - 明示的にenable_transmission=Trueにした場合だけplaceOrderへ進む可能性がある
    - このインスタンスの生涯でplaceOrderは最大1回だけ(プロセス内one-shot)
    - enable_transmission=Trueの送信試行だけ、プロセスを跨いでも有効な
      永続one-shotロック(ファイルの排他作成)で1回だけに制限する
    """

    def __init__(
        self,
        *,
        enable_transmission: bool = False,
        fill_state_path: str
        | Path = "data/ibkr_first_paper_test_fill_state.json",
        lock_path: str | Path = DEFAULT_SEND_LOCK_PATH,
        account_verification_timeout: float = (
            DEFAULT_ACCOUNT_VERIFICATION_TIMEOUT_SECONDS
        ),
    ) -> None:
        self._broker = IbkrBrokerAdapter(
            IbkrConnectionConfig(
                host=REQUIRED_HOST,
                port=REQUIRED_PORT,
                client_id=REQUIRED_CLIENT_ID,
                paper_trading=True,
                allow_live_trading=False,
            ),
            enable_paper_order_transmission=enable_transmission,
            fill_state_path=fill_state_path,
        )
        self._enable_transmission = enable_transmission
        self._lock_path = Path(lock_path)
        self._account_verification_timeout = account_verification_timeout
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

        enable_transmission=Trueで実際に送信を試みる直前だけ、
        プロセスを跨いで有効な永続one-shotロックを安全に確保する。
        ロック取得に失敗した場合(=既に他の実行が送信済み/送信中)は
        placeOrderへ一切進まない。
        Dry Run(enable_transmission=False)ではこのロックを一切消費しない。
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

        if not self._enable_transmission:
            # Dry Run: 永続ロックには一切触れず、既存の安全ロック
            # (enable_transmission=False)にそのまま任せる。
            result = self._broker.place_order(order)
            return self._to_first_test_result(result)

        # ここから先はenable_transmission=Trueかつ、このテスト入口専用の
        # 固定条件(Gateway/AAPL/BUY/1株/Paper/Live禁止)をすべて満たした場合のみ。
        # 実際にplaceOrderへ進む前に、接続先が想定Paper口座であることを
        # 送信直前に確認する(誤口座への送信を防ぐ最終確認)。
        account_blocked = self._verify_required_account()
        if account_blocked is not None:
            return account_blocked

        # 実際にplaceOrderへ進む(=既存の汎用送信経路に処理を委ねる)直前で、
        # プロセスを跨いだ永続one-shotロックを安全に確保する。
        lock_blocked = self._acquire_persistent_send_lock()
        if lock_blocked is not None:
            return lock_blocked

        result = self._broker.place_order(order)
        first_result = self._to_first_test_result(result)

        if not first_result.sent:
            # 実際にはIBKRへ送信されなかったことが確定した場合だけ、
            # 将来の正当な再試行を妨げないよう永続ロックを解放する。
            # (placeOrder呼び出し中に例外が発生した場合はここに到達せず、
            #  送信結果が不明なため安全側に倒してロックを保持したままにする)
            self._release_persistent_send_lock()

        return first_result

    def order_status_snapshot(self, order_id: int) -> float:
        """orderStatus由来の、指定order_idの処理済み累積約定数量を返す。"""
        return self._broker.processed_filled(order_id)

    def _to_first_test_result(self, result) -> IbkrFirstPaperTestResult:
        return IbkrFirstPaperTestResult(
            status=result.status.value,
            sent=result.status is OrderStatus.ACCEPTED,
            order_id=result.order_id,
            message=result.message,
        )

    def _verify_required_account(self) -> IbkrFirstPaperTestResult | None:
        """
        送信直前に、接続先がPaper口座REQUIRED_ACCOUNT_IDであることを確認する。

        IBKR APIは接続確立後にmanagedAccountsを自動送信するが、到着タイミングは
        保証されないため、account_verification_timeout秒までは短い間隔で待つ。
        確認できない(未受信/口座不一致)場合はplaceOrderへ一切進まない。
        この関数自身は注文を一切送信しない。
        """
        session = self._broker._session
        if session is None:
            return IbkrFirstPaperTestResult(
                status="BLOCKED_ACCOUNT_UNVERIFIED",
                sent=False,
                order_id=None,
                message="IBKRセッションが存在しないため口座を確認できませんでした。",
            )

        client = session.client
        deadline = time.monotonic() + self._account_verification_timeout
        accounts = list(getattr(client, "accounts", []))
        while not accounts and time.monotonic() < deadline:
            time.sleep(0.1)
            accounts = list(getattr(client, "accounts", []))

        if REQUIRED_ACCOUNT_ID not in accounts:
            return IbkrFirstPaperTestResult(
                status="BLOCKED_ACCOUNT_MISMATCH",
                sent=False,
                order_id=None,
                message=(
                    f"接続先がPaper口座{REQUIRED_ACCOUNT_ID}であることを"
                    f"確認できなかったため停止しました(受信済み口座: {accounts})。"
                ),
            )

        return None

    def _acquire_persistent_send_lock(self) -> IbkrFirstPaperTestResult | None:
        """
        プロセスを跨いで有効な、排他的なone-shot送信ロックを確保する。

        os.O_CREAT | os.O_EXCLによるファイル作成はOSレベルでアトミックなため、
        複数プロセス(またはスレッド)が同時に呼んでも、ロックファイルを
        実際に作成できるのは1者だけであることが保証される。
        """
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            fd = os.open(
                str(self._lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            return IbkrFirstPaperTestResult(
                status="BLOCKED_ALREADY_SENT",
                sent=False,
                order_id=None,
                message=(
                    "初回Paperテストは既に送信を試行済みです"
                    f"(永続ロック: {self._lock_path})。"
                    "別プロセスからの重複送信をブロックしました。"
                ),
            )

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {"pid": os.getpid(), "acquired_at": time.time()},
                    ensure_ascii=False,
                )
            )

        return None

    def _release_persistent_send_lock(self) -> None:
        self._lock_path.unlink(missing_ok=True)


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
    print(f"CLIENT ID  : {gateway.config.client_id}")
    print(f"PAPER      : {gateway.config.paper_trading}")
    print(f"LIVE ALLOW : {gateway.config.allow_live_trading}")
    print(f"SYMBOL     : {REQUIRED_SYMBOL}")
    print(f"SIDE       : {REQUIRED_SIDE.value}")
    print(f"QUANTITY   : {REQUIRED_QUANTITY}")
    print(f"SEND LOCK  : {gateway._lock_path}")
    print("TRANSMISSION: disabled (this entry point never sends by itself)")


if __name__ == "__main__":
    main()
