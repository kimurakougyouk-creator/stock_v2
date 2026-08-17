from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.execution.order_candidate import OrderCandidate


@dataclass(frozen=True)
class PaperOrderSyncResult:
    candidate: OrderCandidate
    order_request: OrderRequest
    legacy_order: dict[str, Any]


def build_paper_order_sync(
    *,
    ticker: str,
    signal: str,
    shares: int,
    reference_price: float,
) -> PaperOrderSyncResult:
    """
    既存Paper注文データと新Execution注文モデルを
    同じ入力から生成する。

    既存のPaper Tradingを壊さず、
    新Execution経路へ段階的に一本化するための同期層。
    """

    normalized_signal = str(signal).strip().upper()

    if normalized_signal not in {"BUY", "SELL"}:
        raise ValueError("signalはBUYまたはSELLを指定してください。")

    if int(shares) <= 0:
        raise ValueError("sharesは1株以上を指定してください。")

    if float(reference_price) <= 0:
        raise ValueError("reference_priceは0より大きくしてください。")

    side = OrderSide(normalized_signal)

    candidate = OrderCandidate(
        symbol=str(ticker),
        action=normalized_signal,
        quantity=int(shares),
    )

    order_request = OrderRequest(
        symbol=str(ticker),
        side=side,
        quantity=int(shares),
        order_type=OrderType.MARKET,
    )

    legacy_order = {
        "ticker": str(ticker),
        "side": normalized_signal,
        "shares": int(shares),
        "reference_price": float(reference_price),
    }

    return PaperOrderSyncResult(
        candidate=candidate,
        order_request=order_request,
        legacy_order=legacy_order,
    )
