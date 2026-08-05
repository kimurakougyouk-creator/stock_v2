from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig


class _IbkrPaperClient(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)

        self.ready = Event()
        self.next_order_id: int | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_order_id = orderId
        self.ready.set()

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
) -> IbkrPaperSession | None:
    """
    IBKR Paper APIへの持続接続を安全に開始する。

    注文は送信しない。
    Live Tradingは許可しない。
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

    client = _IbkrPaperClient()

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
