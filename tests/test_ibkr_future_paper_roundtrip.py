from ai_asset_platform.brokers.ibkr_future_paper_roundtrip import (
    CONFIRMATION_TEXT,
    CON_ID,
    EXPIRY,
    LOCAL_SYMBOL,
    MULTIPLIER,
    _contract,
    _market_order,
)


def test_exact_broker_resolved_contract_is_pinned():
    contract = _contract()
    assert contract.secType == "FUT"
    assert contract.symbol == "ES"
    assert contract.exchange == "CME"
    assert contract.currency == "USD"
    assert contract.localSymbol == LOCAL_SYMBOL == "ESU6"
    assert contract.lastTradeDateOrContractMonth == EXPIRY == "20260918"
    assert contract.multiplier == MULTIPLIER == "50"
    assert contract.conId == CON_ID == 649180671


def test_real_paper_order_is_market_day_and_transmitted():
    order = _market_order("BUY", "test")
    assert order.action == "BUY"
    assert order.orderType == "MKT"
    assert float(order.totalQuantity) == 1.0
    assert order.tif == "DAY"
    assert order.whatIf is False
    assert order.transmit is True
    assert order.orderRef == "test"


def test_confirmation_text_is_narrow_and_explicit():
    assert CONFIRMATION_TEXT == "YES_BUY_AND_SELL_ONE_ESU6_PAPER_TO_FLAT"
