from types import SimpleNamespace

from ai_asset_platform.brokers import ibkr_option_paper_roundtrip as flow


def _candidate(**overrides):
    values = dict(
        local_symbol=flow.LOCAL_SYMBOL,
        expiry=flow.EXPIRY,
        strike=flow.STRIKE,
        right=flow.RIGHT,
        multiplier=flow.MULTIPLIER,
        con_id=flow.CON_ID,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_proven_option_identity_is_pinned():
    assert flow.SYMBOL == "SPY"
    assert flow.EXCHANGE == "SMART"
    assert flow.CURRENCY == "USD"
    assert flow.EXPIRY == "20260828"
    assert flow.STRIKE == 765.0
    assert flow.RIGHT == "C"
    assert flow.MULTIPLIER == "100"
    assert flow.LOCAL_SYMBOL == "SPY   260828C00765000"
    assert flow.CON_ID == 900369377
    assert flow.QUANTITY == 1


def test_contract_uses_exact_proven_identity():
    contract = flow._contract(_candidate())
    assert contract.secType == "OPT"
    assert contract.symbol == "SPY"
    assert contract.exchange == "SMART"
    assert contract.currency == "USD"
    assert contract.localSymbol == flow.LOCAL_SYMBOL
    assert contract.lastTradeDateOrContractMonth == flow.EXPIRY
    assert contract.strike == flow.STRIKE
    assert contract.right == flow.RIGHT
    assert contract.multiplier == flow.MULTIPLIER
    assert contract.conId == flow.CON_ID


def test_real_paper_order_is_one_market_day_transmitted():
    order = flow._market_order("BUY", "test-ref")
    assert order.action == "BUY"
    assert order.orderType == "MKT"
    assert float(order.totalQuantity) == 1.0
    assert order.tif == "DAY"
    assert order.whatIf is False
    assert order.transmit is True
    assert order.orderRef == "test-ref"


def test_confirmation_text_is_narrow_and_explicit():
    assert flow.CONFIRMATION_TEXT == "YES_BUY_AND_SELL_ONE_SPY_OPTION_PAPER_TO_FLAT"


def test_missing_confirmation_fails_before_broker_access(monkeypatch):
    monkeypatch.delenv("IBKR_OPTION_E2E_CONFIRM", raising=False)
    monkeypatch.setattr(
        flow,
        "SETTINGS",
        SimpleNamespace(
            enable_ibkr_paper=True,
            enable_live_trading=False,
            live_trading_unlocked=False,
        ),
    )
    monkeypatch.setattr(
        flow,
        "_verified_target",
        lambda: (_ for _ in ()).throw(AssertionError("broker discovery must not run")),
    )
    result = flow.run_option_paper_roundtrip(timeout=0.01)
    assert result.attempted is False
    assert "confirmation" in result.reason
    assert result.real_paper_order_sent is False
    assert result.live_order_sent is False


def test_live_lock_fails_before_broker_access(monkeypatch):
    monkeypatch.setenv("IBKR_OPTION_E2E_CONFIRM", flow.CONFIRMATION_TEXT)
    monkeypatch.setattr(
        flow,
        "SETTINGS",
        SimpleNamespace(
            enable_ibkr_paper=True,
            enable_live_trading=True,
            live_trading_unlocked=True,
        ),
    )
    monkeypatch.setattr(
        flow,
        "_verified_target",
        lambda: (_ for _ in ()).throw(AssertionError("broker discovery must not run")),
    )
    result = flow.run_option_paper_roundtrip(timeout=0.01)
    assert result.attempted is False
    assert "Live Trading safety lock" in result.reason
    assert result.real_paper_order_sent is False
    assert result.live_order_sent is False


def test_broker_contract_drift_is_rejected(monkeypatch):
    drifted = _candidate(con_id=flow.CON_ID + 1)
    discovery = SimpleNamespace(
        endpoint_port=4002,
        candidates=(drifted,),
        errors=(),
    )
    monkeypatch.setattr(flow, "discover_ibkr_paper_option", lambda **kwargs: discovery)
    port, candidate, errors = flow._verified_target()
    assert port == 4002
    assert candidate is None
    assert errors == ()


def test_exact_broker_contract_is_accepted(monkeypatch):
    exact = _candidate()
    discovery = SimpleNamespace(
        endpoint_port=4002,
        candidates=(exact,),
        errors=(),
    )
    monkeypatch.setattr(flow, "discover_ibkr_paper_option", lambda **kwargs: discovery)
    port, candidate, errors = flow._verified_target()
    assert port == 4002
    assert candidate is exact
    assert errors == ()
