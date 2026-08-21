from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig
from ai_asset_platform.brokers.ibkr_paper_order_guard import IbkrPaperOrderGuardResult, validate_ibkr_paper_test_order
from ai_asset_platform.brokers.ibkr_paper_order_sender import prepare_ibkr_paper_order, prepare_ibkr_paper_order_for_instrument
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest


class IbkrOrderClient(Protocol):
    def placeOrder(self, order_id: int, contract, order) -> None: ...  # noqa: N802


@dataclass(frozen=True)
class IbkrPaperTransmissionResult:
    status: str
    sent: bool
    order_id: int | None
    message: str


def transmit_ibkr_paper_order(request: OrderRequest, config: IbkrConnectionConfig, *, client: IbkrOrderClient, next_order_id: int | None, enable_transmission: bool = False, guard: IbkrPaperOrderGuardResult | None = None, instrument: InstrumentSpec | None = None, verified_test_quantity: int = 1) -> IbkrPaperTransmissionResult:
    """Send only a Paper order whose quantity was explicitly pre-verified."""
    config.validate()
    if not config.paper_trading or config.allow_live_trading:
        return IbkrPaperTransmissionResult("BLOCKED", False, None, "Paper Trading専用のため送信を停止しました。")

    guard = guard or validate_ibkr_paper_test_order(
        request.symbol,
        request.quantity,
        verified_test_quantity=verified_test_quantity,
        use_gateway=config.port == 4002,
    )
    if not guard.allowed:
        return IbkrPaperTransmissionResult(guard.status, False, None, guard.message)
    if next_order_id is None or next_order_id < 0:
        return IbkrPaperTransmissionResult("WAITING", False, None, "IBKRから有効なnextValidIdを取得できていないため送信しません。")

    prepared = prepare_ibkr_paper_order_for_instrument(request, instrument, config) if instrument is not None else prepare_ibkr_paper_order(request, config)
    if not enable_transmission:
        return IbkrPaperTransmissionResult("READY_NOT_SENT", False, next_order_id, "Paper注文は送信可能ですが、安全ロックにより未送信です。")

    prepared.order.transmit = True
    client.placeOrder(next_order_id, prepared.contract, prepared.order)
    return IbkrPaperTransmissionResult("SENT", True, next_order_id, "IBKR Paper APIへテスト注文を送信しました。")
