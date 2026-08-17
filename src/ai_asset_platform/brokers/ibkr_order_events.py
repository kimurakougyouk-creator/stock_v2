from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class IbkrOrderState(str, Enum):
    PENDING_SUBMIT = "PendingSubmit"
    PRE_SUBMITTED = "PreSubmitted"
    SUBMITTED = "Submitted"
    FILLED = "Filled"
    PENDING_CANCEL = "PendingCancel"
    CANCELLED = "Cancelled"
    API_CANCELLED = "ApiCancelled"
    INACTIVE = "Inactive"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class IbkrOrderStatusEvent:
    order_id: int
    status: IbkrOrderState
    filled: float
    remaining: float
    average_fill_price: float

    @property
    def is_complete(self) -> bool:
        return self.status is IbkrOrderState.FILLED and self.remaining == 0

    @property
    def has_fill(self) -> bool:
        return self.filled > 0


def normalize_ibkr_order_state(status: str) -> IbkrOrderState:
    try:
        return IbkrOrderState(status)
    except ValueError:
        return IbkrOrderState.UNKNOWN


def create_ibkr_order_status_event(
    order_id: int,
    status: str,
    filled: float,
    remaining: float,
    average_fill_price: float,
) -> IbkrOrderStatusEvent:
    if order_id < 0:
        raise ValueError("IBKR order_idは0以上にしてください。")

    if filled < 0:
        raise ValueError("filledは0以上にしてください。")

    if remaining < 0:
        raise ValueError("remainingは0以上にしてください。")

    if average_fill_price < 0:
        raise ValueError("average_fill_priceは0以上にしてください。")

    return IbkrOrderStatusEvent(
        order_id=order_id,
        status=normalize_ibkr_order_state(status),
        filled=filled,
        remaining=remaining,
        average_fill_price=average_fill_price,
    )
