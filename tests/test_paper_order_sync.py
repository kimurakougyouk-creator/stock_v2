import pytest

from ai_asset_platform.brokers.orders import OrderSide, OrderType
from ai_asset_platform.execution.paper_order_sync import build_paper_order_sync


def test_build_buy_paper_order_sync():
    result = build_paper_order_sync(
        ticker="7203.T",
        signal="BUY",
        shares=100,
        reference_price=2500.0,
    )

    assert result.candidate.symbol == "7203.T"
    assert result.candidate.action == "BUY"
    assert result.candidate.quantity == 100

    assert result.order_request.symbol == "7203.T"
    assert result.order_request.side is OrderSide.BUY
    assert result.order_request.quantity == 100
    assert result.order_request.order_type is OrderType.MARKET

    assert result.legacy_order == {
        "ticker": "7203.T",
        "side": "BUY",
        "shares": 100,
        "reference_price": 2500.0,
    }


def test_build_sell_paper_order_sync():
    result = build_paper_order_sync(
        ticker="7203.T",
        signal="SELL",
        shares=50,
        reference_price=2700.0,
    )

    assert result.candidate.action == "SELL"
    assert result.order_request.side is OrderSide.SELL
    assert result.order_request.quantity == 50
    assert result.legacy_order["side"] == "SELL"


def test_build_paper_order_sync_rejects_invalid_signal():
    with pytest.raises(ValueError, match="BUYまたはSELL"):
        build_paper_order_sync(
            ticker="7203.T",
            signal="HOLD",
            shares=100,
            reference_price=2500.0,
        )


def test_build_paper_order_sync_rejects_invalid_shares():
    with pytest.raises(ValueError, match="1株以上"):
        build_paper_order_sync(
            ticker="7203.T",
            signal="BUY",
            shares=0,
            reference_price=2500.0,
        )


def test_build_paper_order_sync_rejects_invalid_price():
    with pytest.raises(ValueError, match="0より大きく"):
        build_paper_order_sync(
            ticker="7203.T",
            signal="BUY",
            shares=100,
            reference_price=0.0,
        )
