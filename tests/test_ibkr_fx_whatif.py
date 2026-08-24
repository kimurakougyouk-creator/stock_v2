from pathlib import Path

import pytest

from ai_asset_platform.brokers.ibkr_fx_whatif import (
    IbkrFxWhatIfResult,
    _build_total_quantity_whatif_order,
)
from ai_asset_platform.brokers.ibkr_fx_whatif_intent import (
    FxQuantityMode,
    FxWhatIfIntentInput,
    verify_fx_whatif_intent,
)
from ai_asset_platform.brokers.orders import OrderSide


def _verified_intent(*, mode=FxQuantityMode.TOTAL_QUANTITY, quantity=1000.0):
    return verify_fx_whatif_intent(
        FxWhatIfIntentInput(
            base_currency="USD",
            quote_currency="JPY",
            exchange="IDEALPRO",
            con_id=12345,
            local_symbol="USD.JPY",
            side=OrderSide.BUY,
            quantity_mode=mode,
            quantity=quantity,
            limit_price=158.5,
            min_size=(1.0 if mode is FxQuantityMode.TOTAL_QUANTITY else None),
            size_increment=(1.0 if mode is FxQuantityMode.TOTAL_QUANTITY else None),
        )
    )


def test_built_fx_preview_order_is_always_whatif_and_never_market_order():
    order = _build_total_quantity_whatif_order(intent=_verified_intent())
    assert order.action == "BUY"
    assert order.orderType == "LMT"
    assert order.totalQuantity == 1000
    assert order.lmtPrice == 158.5
    assert order.whatIf is True
    assert order.transmit is True
    assert order.orderRef == "stock_v2-fx-whatif"


def test_cash_quantity_remains_blocked_from_broker_preview():
    with pytest.raises(RuntimeError, match="TOTAL_QUANTITY only"):
        _build_total_quantity_whatif_order(
            intent=_verified_intent(mode=FxQuantityMode.CASH_QUANTITY, quantity=100000.0)
        )


def test_fractional_total_quantity_remains_blocked():
    with pytest.raises(ValueError, match="not aligned"):
        _verified_intent(quantity=1000.5)


def test_ready_requires_preview_and_never_real_order():
    ready = IbkrFxWhatIfResult(
        connected=True,
        discovery_resolved=True,
        preview_received=True,
        base_currency="USD",
        quote_currency="JPY",
        exchange="IDEALPRO",
        side="BUY",
        quantity_mode="TOTAL_QUANTITY",
        quantity=1000.0,
        limit_price=158.5,
        con_id=12345,
        endpoint_port=4002,
        whatif_submitted=True,
        real_order_sent=False,
    )
    assert ready.ready is True

    not_ready = IbkrFxWhatIfResult(
        connected=True,
        discovery_resolved=True,
        preview_received=True,
        base_currency="USD",
        quote_currency="JPY",
        exchange="IDEALPRO",
        side="BUY",
        quantity_mode="TOTAL_QUANTITY",
        quantity=1000.0,
        limit_price=158.5,
        con_id=12345,
        endpoint_port=4002,
        whatif_submitted=True,
        real_order_sent=True,
    )
    assert not_ready.ready is False


def test_fx_whatif_module_has_no_live_unlock_or_real_order_mode():
    text = Path("src/ai_asset_platform/brokers/ibkr_fx_whatif.py").read_text(encoding="utf-8")
    assert "AI_ASSET_ENABLE_LIVE" not in text
    assert "allow_live_trading=True" not in text
    assert "real_order_sent=True" not in text
    assert "whatIf = False" not in text
    assert "cancelOrder(" not in text
