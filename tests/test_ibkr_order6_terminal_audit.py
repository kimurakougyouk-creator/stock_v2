from ai_asset_platform.brokers.ibkr_order6_terminal_audit import classify


def test_open_order_waits_without_resend():
    assert classify({"status": "Submitted"}, []) == "WAIT_NO_RESEND"


def test_full_execution_confirms_fill():
    assert classify(None, [{"shares": 100.0}]) == "FILLED_EXECUTION_CONFIRMED"


def test_multiple_executions_confirm_full_fill():
    assert classify(None, [{"shares": 40.0}, {"shares": 60.0}]) == "FILLED_EXECUTION_CONFIRMED"


def test_partial_execution_without_open_order_requires_verification():
    assert classify(None, [{"shares": 50.0}]) == "PARTIAL_EXECUTION_NOT_OPEN_VERIFY"


def test_disappearance_alone_never_claims_fill():
    assert classify(None, []) == "NOT_OPEN_TERMINAL_UNCONFIRMED"
