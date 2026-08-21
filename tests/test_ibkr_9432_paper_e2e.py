from ai_asset_platform.brokers.ibkr_9432_paper_e2e import (
    ORDER_INTENT_ID,
    QUANTITY,
    SYMBOL,
    build_instrument,
)


def test_9432_e2e_uses_broker_verified_contract_and_quantity():
    instrument = build_instrument()
    assert SYMBOL == "9432"
    assert QUANTITY == 100
    assert instrument.symbol == "9432"
    assert instrument.exchange == "TSEJ"
    assert instrument.currency == "JPY"
    assert instrument.verified_paper_test_quantity == 100


def test_9432_e2e_has_stable_idempotency_key():
    assert ORDER_INTENT_ID == "9432-paper-e2e-verified-lot-v1"
