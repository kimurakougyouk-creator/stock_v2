from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread
from typing import Callable

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig


OrderStatusHandler = Callable[[int, str, float, float, float], None]


class _IbkrPaperClient(EWrapper, EClient):
    def __init__(
        self,
        *,
        order_status_handler: OrderStatusHandler | None = None,
    ) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)

        self.ready = Event()
        self.next_order_id: int | None = None
        self._order_status_handler = order_status_handler

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = orderId
        self.ready.set()

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

    def error(
        self,
        reqId,
        errorCode,
        errorString,
        advancedOrderRejectJson="",
    ):
        if errorCode in {502, 503, 504, 1100}:
            self.ready.set()


@dataclass
class IbkrPaperSession:
    client: _IbkrPaperClient
    next_order_id: int

    @property
    def connected(self) -> bool:
        return self.client.isConnected()

    def disconnect(self) -> None:
        if self.client.isConnected():
            self.client.disconnect()


def open_ibkr_paper_session(
    config: IbkrConnectionConfig,
    *,
    timeout: float = 5.0,
    order_status_handler: OrderStatusHandler | None = None,
) -> IbkrPaperSession | None:
    """
    IBKR Paper APIへの持続接続を安全に開始する。

    注文は送信しない。
    Live Tradingは許可しない。
    orderStatusは指定された安全なハンドラへ渡す。
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
    )

    try:
        client.connect(
            config.host,
            config.port,
            config.client_id,
        )

        thread = Thread(
            target=client.run,
            daemon=True,
        )
        thread.start()

        client.ready.wait(timeout)

        if (
            client.next_order_id is None
            or not client.isConnected()
        ):
            if client.isConnected():
                client.disconnect()
            return None

        return IbkrPaperSession(
            client=client,
            next_order_id=client.next_order_id,
        )

    except Exception:
        if client.isConnected():
            client.disconnect()
        raise
