from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderLimitReason:
    code: str
    message: str
    limit_shares: int


def detect_buy_order_limit_reason(
    *,
    requested_shares: int,
    affordable_shares: int,
    allocation_limit_shares: int,
    risk_limit_shares: int,
    portfolio_risk_limit_shares: int,
) -> OrderLimitReason | None:
    """
    BUY注文を最も強く制限している安全条件を返す。
    """

    limits = [
        (
            "AVAILABLE_CASH",
            "利用可能資金",
            affordable_shares,
        ),
        (
            "POSITION_ALLOCATION",
            "1銘柄あたりの資金配分上限",
            allocation_limit_shares,
        ),
        (
            "TRADE_RISK",
            "1取引あたりの損失許容額",
            risk_limit_shares,
        ),
        (
            "PORTFOLIO_RISK",
            "全保有ポジションの合計リスク上限",
            portfolio_risk_limit_shares,
        ),
    ]

    limiting_code, limiting_message, limiting_shares = min(
        limits,
        key=lambda item: item[2],
    )

    if limiting_shares >= requested_shares:
        return None

    return OrderLimitReason(
        code=limiting_code,
        message=limiting_message,
        limit_shares=limiting_shares,
    )
