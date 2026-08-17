from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig


@dataclass(frozen=True)
class IbkrConnectionResult:
    connected: bool
    next_order_id: int | None
    message: str


class _ConnectionProbe(EWrapper, EClient):
    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, self)
        self.ready = Event()
        self.next_valid_order_id: int | None = None

    def nextValidId(self, orderId: int) -> None:  # noqa: N802
        self.next_valid_order_id = orderId
        self.ready.set()

    def error(
        self,
        reqId,
        errorTime,
        errorCode,
        errorString,
        advancedOrderRejectJson="",
    ):
        if errorCode in {502, 503, 504, 1100}:
            self.ready.set()


def probe_ibkr_paper_connection(
    config: IbkrConnectionConfig,
    *,
    timeout: float = 5.0,
) -> IbkrConnectionResult:
    """IBKR Paper TWS/Gatewayへ接続だけを試す。注文は送信しない。"""
    config.validate()

    if not config.paper_trading:
        raise RuntimeError(
            "Paper Trading設定ではないためIBKR接続診断を中止しました。"
        )

    if config.allow_live_trading:
        raise RuntimeError(
            "Live Trading許可中のためIBKR接続診断を中止しました。"
        )

    probe = _ConnectionProbe()

    try:
        probe.connect(config.host, config.port, config.client_id)
        thread = Thread(target=probe.run, daemon=True)
        thread.start()
        probe.ready.wait(timeout)

        if probe.next_valid_order_id is None:
            return IbkrConnectionResult(
                connected=False,
                next_order_id=None,
                message=(
                    "IBKR Paper APIとの接続を確認できませんでした。"
                    "TWS/IB Gatewayの起動とAPI設定を確認してください。"
                ),
            )

        return IbkrConnectionResult(
            connected=True,
            next_order_id=probe.next_valid_order_id,
            message="IBKR Paper APIとの接続を確認しました。",
        )
    finally:
        if probe.isConnected():
            probe.disconnect()
