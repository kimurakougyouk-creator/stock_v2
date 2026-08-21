from ai_asset_platform.brokers.ibkr_open_order_audit import TARGET_ORDER_ID


def test_open_order_audit_targets_existing_order_only():
    assert TARGET_ORDER_ID == 6
