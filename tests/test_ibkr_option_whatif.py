from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_option_whatif as module


def test_candidate_order_is_small_and_deterministic():
    assert module.CANDIDATE_EXPIRIES == ("20260828", "20260831")
    assert module.CANDIDATE_STRIKES[:3] == (765.0, 770.0, 760.0)


def test_result_ready_requires_preview_and_no_real_orders():
    result = module.OptionWhatIfResult(
        connected=True,
        resolved=True,
        preview_received=True,
        endpoint_port=4002,
        local_symbol="SPY   260828C00765000",
        expiry="20260828",
        strike=765.0,
        right="C",
        multiplier="100",
        con_id=123,
        margin_change=0.0,
        commission=None,
        commission_currency=None,
        warning=None,
        errors=(),
        real_order_sent=False,
        live_order_sent=False,
    )
    assert result.ready is True


def test_resolve_target_requires_exact_single_contract(monkeypatch):
    candidate = SimpleNamespace(
        con_id=123,
        local_symbol="SPY   260828C00765000",
        expiry="20260828",
        strike=765.0,
        right="C",
        multiplier="100",
    )
    monkeypatch.setattr(
        module,
        "discover_ibkr_paper_option",
        lambda **kwargs: SimpleNamespace(
            endpoint_port=4002,
            candidates=(candidate,),
            errors=(),
        ),
    )
    port, selected, errors = module._resolve_target()
    assert port == 4002
    assert selected is candidate
    assert errors == ()
