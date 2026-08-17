from ai_asset_platform.decision.signal_selector import (
    TradingSignal,
    select_best_signal,
)


def test_select_best_signal():
    signals = [
        TradingSignal("7203.T", "BUY", 72.0),
        TradingSignal("6758.T", "BUY", 91.5),
        TradingSignal("9984.T", "BUY", 85.0),
    ]

    best = select_best_signal(signals)

    assert best is not None
    assert best.symbol == "6758.T"
    assert best.confidence == 91.5


def test_select_best_signal_empty():
    assert select_best_signal([]) is None
