from ai_asset_platform.decision.signal_selector import TradingSignal
from ai_asset_platform.execution.order_candidate import (
    OrderCandidate,
    create_order_candidate,
)


def test_create_order_candidate_default_quantity():
    signal = TradingSignal(
        symbol="7203.T",
        action="BUY",
        confidence=92.5,
    )

    order = create_order_candidate(signal)

    assert isinstance(order, OrderCandidate)
    assert order.symbol == "7203.T"
    assert order.action == "BUY"
    assert order.quantity == 100


def test_create_order_candidate_custom_quantity():
    signal = TradingSignal(
        symbol="6758.T",
        action="SELL",
        confidence=88.0,
    )

    order = create_order_candidate(signal, quantity=50)

    assert order.quantity == 50
    assert order.action == "SELL"
