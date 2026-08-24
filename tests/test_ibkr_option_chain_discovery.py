from ai_asset_platform.brokers.ibkr_option_chain_discovery import _Probe, OptionChainDiscoveryResult


def test_option_parameter_callback_preserves_broker_fields():
    probe = _Probe()
    probe.securityDefinitionOptionParameter(
        2, "SMART", 756733, "SPY", "100", {"20260828", "20260904"}, {500.0, 510.0}
    )
    assert len(probe.params) == 1
    row = probe.params[0]
    assert row.exchange == "SMART"
    assert row.underlying_con_id == 756733
    assert row.trading_class == "SPY"
    assert row.multiplier == "100"
    assert row.expirations == ("20260828", "20260904")
    assert row.strikes == (500.0, 510.0)


def test_ready_requires_underlying_and_chain_and_no_order():
    empty = OptionChainDiscoveryResult(True, 4002, "SPY", 756733, (), (), False)
    assert empty.ready is False
    candidate = _Probe()
    candidate.securityDefinitionOptionParameter(2, "SMART", 756733, "SPY", "100", {"20260828"}, {500.0})
    ready = OptionChainDiscoveryResult(True, 4002, "SPY", 756733, tuple(candidate.params), (), False)
    assert ready.ready is True
    assert ready.order_sent is False
