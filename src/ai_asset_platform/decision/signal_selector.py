from dataclasses import dataclass


@dataclass(frozen=True)
class TradingSignal:
    symbol: str
    action: str
    confidence: float


def select_best_signal(
    signals: list[TradingSignal],
) -> TradingSignal | None:
    if not signals:
        return None

    return max(signals, key=lambda signal: signal.confidence)
