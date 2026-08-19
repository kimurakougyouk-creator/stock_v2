from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread
from typing import Callable

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig


OrderStatusHandler = Callable[[int, str, float, float, float], None]
ExecutionHandler = Callable[[int, str, float, float], None]


class _IbkrPaperClient(EWrapper, EClient):
    def __init__(
        self,
        *,
        order_status_handler: OrderStatusHandler | None = None,
        exec_details_handler: ExecutionHandler | None = None,
    ) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)

        self.ready = Event()
        self.next_order_id: int | None = None
        self.accounts: list[str] = []
        self.server_version: int | None = None
        # 観測専用のバッファ。注文変更・取消・再送信は一切行わない。
        self.errors: list[dict] = []
        self.open_orders: dict[int, dict] = {}
        self.executions: list[dict] = []
        self.message_loop_exception: BaseException | None = None
        self.message_loop_finished = Event()
        self._order_status_handler = order_status_handler
        self._exec_details_handler = exec_details_handler

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = orderId
        self.server_version = self.serverVersion()
        self.ready.set()

    def managedAccounts(self, accountsList: str) -> None:  # noqa: N802
        self.accounts = [
            account.strip() for account in accountsList.split(",") if account.strip()
        ]

    def orderStatus(  # noqa: N802
        self,
        orderId,
        status,
        filled,
        remaining,
        avgFillPrice,
        permId,
        parentId,
        lastFillPrice,
        clientId,
        whyHeld,
        mktCapPrice,
    ) -> None:
        if self._order_status_handler is None:
            return

        self._order_status_handler(
            int(orderId),
            str(status),
            float(filled),
            float(remaining),
            float(avgFillPrice),
        )

    def execDetails(  # noqa: N802
        self,
        reqId,
        contract,
        execution,
    ) -> None:
        # 観測用に生イベントを保持する(ハンドラ未登録でも見えるようにするため)。
        self.executions.append(
            {
                "req_id": reqId,
                "order_id": int(execution.orderId),
                "exec_id": str(execution.execId),
                "shares": float(execution.shares),
                "price": float(execution.price),
            }
        )

        if self._exec_details_handler is None:
            return

        self._exec_details_handler(
            int(execution.orderId),
            str(execution.execId),
            float(execution.shares),
            float(execution.price),
        )

    def openOrder(  # noqa: N802
        self,
        orderId,
        contract,
        order,
        orderState,
    ) -> None:
        """openOrderの観測専用ハンドラ。注文の変更・取消は一切行わない。"""
        self.open_orders[int(orderId)] = {
            "order_id": int(orderId),
            "symbol": getattr(contract, "symbol", None),
            "action": getattr(order, "action", None),
            "quantity": float(getattr(order, "totalQuantity", 0) or 0),
            "order_type": getattr(order, "orderType", None),
            "status": getattr(orderState, "status", None),
        }

    def error(
        self,
        reqId,
        errorTime,
        errorCode,
        errorString,
        advancedOrderRejectJson="",
    ):
        # 観測用に全コード・全メッセージを保持する(既存の接続用ready.set()は維持)。
        self.errors.append(
            {
                "req_id": reqId,
                "error_time": errorTime,
                "code": int(errorCode),
                "message": str(errorString),
                "advanced_order_reject_json": advancedOrderRejectJson,
            }
        )

        if errorCode in {502, 503, 504, 1100}:
            self.ready.set()


@dataclass(frozen=True)
class IbkrConnectionDiagnostics:
    """接続・メッセージループの状態を読み取り専用で報告するためのスナップショット。"""

    server_version: int | None
    next_valid_id: int | None
    is_connected: bool
    message_loop_alive: bool
    message_loop_exception: str | None


@dataclass
class IbkrPaperSession:
    client: _IbkrPaperClient
    next_order_id: int
    # 既存呼び出し側(fill runtime配線テスト等)は実スレッドを持たないため、
    # 後方互換のためoptionalにする。実接続(open_ibkr_paper_session)は必ず渡す。
    thread: Thread | None = None

    @property
    def connected(self) -> bool:
        return self.client.isConnected()

    @property
    def message_loop_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def diagnostics(self) -> IbkrConnectionDiagnostics:
        exc = self.client.message_loop_exception
        return IbkrConnectionDiagnostics(
            server_version=self.client.server_version,
            next_valid_id=self.client.next_order_id,
            is_connected=self.client.isConnected(),
            message_loop_alive=self.message_loop_alive,
            message_loop_exception=repr(exc) if exc is not None else None,
        )

    def disconnect(self) -> None:
        if self.client.isConnected():
            self.client.disconnect()


def _run_message_loop(client: _IbkrPaperClient) -> None:
    """client.run()を観測付きで実行する。挙動自体は変更しない。

    EClient.run()は内部でfinallyブロックからdisconnect()を呼ぶ設計であり、
    想定外の例外はここまで伝播しうる。その場合でもプロセス全体やスレッドの
    挙動は変えず、後から診断できるようclientへ記録するだけに留める。
    """
    try:
        client.run()
    except BaseException as exc:  # noqa: BLE001 - 観測専用、再送出はしない
        client.message_loop_exception = exc
    finally:
        client.message_loop_finished.set()


FailedConnectObserver = Callable[[_IbkrPaperClient, Thread], None]


def open_ibkr_paper_session(
    config: IbkrConnectionConfig,
    *,
    timeout: float = 5.0,
    order_status_handler: OrderStatusHandler | None = None,
    exec_details_handler: ExecutionHandler | None = None,
    on_failed_connect: FailedConnectObserver | None = None,
) -> IbkrPaperSession | None:
    """
    IBKR Paper APIへの持続接続を安全に開始する。

    注文は送信しない。
    Live Tradingは許可しない。
    orderStatus/execDetailsは指定された安全なハンドラへ渡す。

    接続に失敗した場合、内部のclient/threadはそのまま破棄され戻り値はNoneに
    なるため、失敗直前に観測したerrors/diagnosticsは通常失われる。
    on_failed_connectを渡すと、破棄する直前に一度だけ(client, thread)を渡す。
    これは観測専用のフックであり、再接続やリトライは一切行わない。
    """
    config.validate()

    if not config.paper_trading:
        raise RuntimeError(
            "Paper Trading設定ではないため接続を中止しました。"
        )

    if config.allow_live_trading:
        raise RuntimeError(
            "Live Trading許可中のため接続を中止しました。"
        )

    client = _IbkrPaperClient(
        order_status_handler=order_status_handler,
        exec_details_handler=exec_details_handler,
    )

    try:
        client.connect(
            config.host,
            config.port,
            config.client_id,
        )

        thread = Thread(
            target=_run_message_loop,
            args=(client,),
            daemon=True,
        )
        thread.start()

        client.ready.wait(timeout)

        if (
            client.next_order_id is None
            or not client.isConnected()
        ):
            if on_failed_connect is not None:
                on_failed_connect(client, thread)
            if client.isConnected():
                client.disconnect()
            return None

        return IbkrPaperSession(
            client=client,
            next_order_id=client.next_order_id,
            thread=thread,
        )

    except Exception:
        if client.isConnected():
            client.disconnect()
        raise
