from types import SimpleNamespace

from ai_asset_platform.brokers.ibkr_order_size_audit import extract_order_size_rule


def test_extract_order_size_rule_reads_ibkr_contract_details_fields():
    details = SimpleNamespace(
        contract=SimpleNamespace(symbol="9432"),
        minSize=100,
        sizeIncrement=100,
        suggestedSizeIncrement=100,
    )

    rule = extract_order_size_rule(details)

    assert rule.symbol == "9432"
    assert rule.min_size == 100.0
    assert rule.size_increment == 100.0
    assert rule.suggested_size_increment == 100.0


def test_extract_order_size_rule_fails_closed_on_missing_or_invalid_values():
    details = SimpleNamespace(
        contract=SimpleNamespace(symbol="9432"),
        minSize=None,
        sizeIncrement=0,
        suggestedSizeIncrement="",
    )

    rule = extract_order_size_rule(details)

    assert rule.min_size is None
    assert rule.size_increment is None
    assert rule.suggested_size_increment is None
