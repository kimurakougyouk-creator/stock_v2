from dataclasses import dataclass

from ai_asset_platform.decision.signal_selector import TradingSignal


@dataclass(frozen=True)
class OrderCandidate:
    symbol: str
    action: str
    quantity: int


def create_order_candidate(
    signal: TradingSignal,
    quantity: int = 100,
) -> OrderCandidate:
    return OrderCandidate(
        symbol=signal.symbol,
        action=signal.action,
        quantity=quantity,
    )
