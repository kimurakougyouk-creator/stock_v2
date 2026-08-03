from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_paper_order_guard import (
    IbkrPaperOrderGuardResult,
    validate_ibkr_paper_test_order,
)
from ai_asset_platform.brokers.ibkr_paper_order_sender import (
    prepare_ibkr_paper_order,
)
from ai_asset_platform.brokers.orders import OrderRequest


class IbkrOrderClient(Protocol):
    def placeOrder(self, order_id: int, contract, order) -> None: ...  # noqa: N802


@dataclass(frozen=True)
class IbkrPaperTransmissionResult:
    status: str
    sent: bool
    order_id: int | None
    message: str


def transmit_ibkr_paper_order(
    request: OrderRequest,
    config: IbkrConnectionConfig,
    *,
    client: IbkrOrderClient,
    next_order_id: int | None,
    enable_transmission: bool = False,
    guard: IbkrPaperOrderGuardResult | None = None,
) -> IbkrPaperTransmissionResult:
    """IBKR Paper注文を安全条件成立時だけ送信する。

    デフォルトは enable_transmission=False なので、明示的に有効化しない限り
    placeOrder は呼ばれない。Live Trading は常に拒否する。
    """
    config.validate()

    if not config.paper_trading or config.allow_live_trading:
        return IbkrPaperTransmissionResult(
            status="BLOCKED",
            sent=False,
            order_id=None,
            message="Paper Trading専用のため送信を停止しました。",
        )

    guard = guard or validate_ibkr_paper_test_order(
        request.symbol,
        request.quantity,
    )
    if not guard.allowed:
        return IbkrPaperTransmissionResult(
            status=guard.status,
            sent=False,
            order_id=None,
            message=guard.message,
        )

    if next_order_id is None or next_order_id < 0:
        return IbkrPaperTransmissionResult(
            status="WAITING",
            sent=False,
            order_id=None,
            message="IBKRから有効なnextValidIdを取得できていないため送信しません。",
        )

    prepared = prepare_ibkr_paper_order(request, config)

    if not enable_transmission:
        return IbkrPaperTransmissionResult(
            status="READY_NOT_SENT",
            sent=False,
            order_id=next_order_id,
            message="Paper注文は送信可能ですが、安全ロックにより未送信です。",
        )

    # ここに到達するのはPaper限定・数量1・事前ガード成功・nextValidId取得済み、
    # かつ呼び出し側が明示的に送信を許可した場合だけ。
    prepared.order.transmit = True
    client.placeOrder(next_order_id, prepared.contract, prepared.order)

    return IbkrPaperTransmissionResult(
        status="SENT",
        sent=True,
        order_id=next_order_id,
        message="IBKR Paper APIへテスト注文を送信しました。",
    )
