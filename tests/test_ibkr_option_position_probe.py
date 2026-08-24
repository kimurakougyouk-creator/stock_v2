from ai_asset_platform.brokers import ibkr_option_position_probe as probe


def test_quantity_no_match_is_flat_zero():
    assert probe._quantity([]) == 0.0


def test_quantity_identical_duplicate_callbacks_are_deduped():
    rows = [
        (probe.LOCAL_SYMBOL.upper(), "OPT", 0.0),
        (probe.LOCAL_SYMBOL.upper(), "OPT", 0.0),
    ]
    assert probe._quantity(rows) == 0.0


def test_quantity_conflicting_duplicate_callbacks_fail_closed():
    rows = [
        (probe.LOCAL_SYMBOL.upper(), "OPT", 0.0),
        (probe.LOCAL_SYMBOL.upper(), "OPT", 1.0),
    ]
    try:
        probe._quantity(rows)
    except RuntimeError as exc:
        assert "conflicting duplicate" in str(exc)
    else:
        raise AssertionError("conflicting duplicate callbacks must fail closed")


def test_probe_source_contains_no_order_submission_path():
    import inspect
    source = inspect.getsource(probe)
    assert "placeOrder(" not in source
    assert "Order()" not in source
