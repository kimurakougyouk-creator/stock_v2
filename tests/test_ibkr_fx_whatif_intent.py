from pathlib import Path

import pytest

from ai_asset_platform.brokers.ibkr_fx_whatif_intent import (
    FxQuantityMode,
    FxWhatIfIntentInput,
    verify_fx_whatif_intent,
)
from ai_asset_platform.brokers.orders import OrderSide


def _spec(**overrides):
    values = dict(
        base_currency="USD",
        quote_currency="JPY",
        exchange="IDEALPRO",
        con_id=12345,
        side=OrderSide.BUY,
        quantity_mode=FxQuantityMode.TOTAL_QUANTITY,
        quantity=1000.0,
        limit_price=158.5,
        local_symbol="USD.JPY",
        min_size=1.0,
        size_increment=1.0,
    )
    values.update(overrides)
    return FxWhatIfIntentInput(**values)


def test_verified_fx_whatif_intent_is_explicit_and_never_real_order_permission():
    result = verify_fx_whatif_intent(_spec())
    assert result.contract_input.base_currency == "USD"
    assert result.contract_input.quote_currency == "JPY"
    assert result.contract_input.exchange == "IDEALPRO"
    assert result.contract_input.con_id == 12345
    assert result.side is OrderSide.BUY
    assert result.quantity_mode is FxQuantityMode.TOTAL_QUANTITY
    assert result.real_order_allowed is False


def test_cash_quantity_mode_must_be_explicit_but_is_intent_only():
    result = verify_fx_whatif_intent(
        _spec(
            quantity_mode=FxQuantityMode.CASH_QUANTITY,
            quantity=100000.0,
            min_size=None,
            size_increment=None,
        )
    )
    assert result.quantity_mode is FxQuantityMode.CASH_QUANTITY
    assert result.min_size is None
    assert result.size_increment is None
    assert result.real_order_allowed is False


def test_cash_quantity_does_not_reuse_total_quantity_size_constraints_by_assumption():
    with pytest.raises(ValueError, match="CASH_QUANTITY.*semantics are unverified"):
        verify_fx_whatif_intent(
            _spec(
                quantity_mode=FxQuantityMode.CASH_QUANTITY,
                quantity=100000.0,
            )
        )


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_quantity_must_be_finite_and_positive(value):
    with pytest.raises(ValueError, match="quantity"):
        verify_fx_whatif_intent(_spec(quantity=value))


def test_quantity_cannot_be_below_broker_min_size():
    with pytest.raises(ValueError, match="below broker min_size"):
        verify_fx_whatif_intent(_spec(quantity=0.5, min_size=1.0, size_increment=None))


def test_quantity_must_align_with_broker_increment():
    with pytest.raises(ValueError, match="not aligned"):
        verify_fx_whatif_intent(_spec(quantity=1000.5, size_increment=1.0))


def test_pair_exchange_and_conid_are_never_inferred():
    with pytest.raises(ValueError):
        verify_fx_whatif_intent(_spec(exchange=""))
    with pytest.raises(ValueError):
        verify_fx_whatif_intent(_spec(con_id=0))
    with pytest.raises(ValueError):
        verify_fx_whatif_intent(_spec(base_currency="USD", quote_currency="USD"))


def test_side_and_quantity_mode_must_be_enums_not_strings():
    with pytest.raises(ValueError, match="explicit OrderSide"):
        verify_fx_whatif_intent(_spec(side="BUY"))
    with pytest.raises(ValueError, match="quantity_mode must be explicit"):
        verify_fx_whatif_intent(_spec(quantity_mode="TOTAL_QUANTITY"))


def test_intent_module_contains_no_broker_connection_or_order_transmission_path():
    text = Path(
        "src/ai_asset_platform/brokers/ibkr_fx_whatif_intent.py"
    ).read_text(encoding="utf-8")
    assert "EClient" not in text
    assert "placeOrder(" not in text
    assert "cancelOrder(" not in text
    assert "Order()" not in text
    assert "enable_paper_order_transmission" not in text
    assert "allow_live_trading" not in text
