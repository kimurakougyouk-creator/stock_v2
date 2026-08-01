from ai_asset_platform.brokers.orders import OrderSide
from ai_asset_platform.execution.paper_order_sync import build_paper_order_sync


def test_signal_runner_paper_order_sync_buy():
    sync = build_paper_order_sync(
        ticker="7203.T",
        signal="BUY",
        shares=100,
        reference_price=2500.0,
    )

    assert sync.candidate.symbol == "7203.T"
    assert sync.candidate.action == "BUY"
    assert sync.candidate.quantity == 100

    assert sync.order_request.symbol == "7203.T"
    assert sync.order_request.side is OrderSide.BUY
    assert sync.order_request.quantity == 100

    assert sync.legacy_order["ticker"] == "7203.T"
    assert sync.legacy_order["side"] == "BUY"
    assert sync.legacy_order["shares"] == 100
    assert sync.legacy_order["reference_price"] == 2500.0


def test_signal_runner_paper_order_sync_sell():
    sync = build_paper_order_sync(
        ticker="7203.T",
        signal="SELL",
        shares=50,
        reference_price=2700.0,
    )

    assert sync.candidate.action == "SELL"
    assert sync.order_request.side is OrderSide.SELL
    assert sync.legacy_order["side"] == "SELL"
