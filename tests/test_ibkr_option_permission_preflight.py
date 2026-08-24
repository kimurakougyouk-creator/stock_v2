from types import SimpleNamespace

from ai_asset_platform.brokers import ibkr_option_permission_preflight as preflight


def _candidate(**overrides):
    values = dict(
        con_id=preflight.CON_ID,
        local_symbol=preflight.LOCAL_SYMBOL,
        expiry=preflight.EXPIRY,
        strike=preflight.STRIKE,
        right=preflight.RIGHT,
        multiplier=preflight.MULTIPLIER,
        order_types="LMT,MKT,STP",
        valid_exchanges="SMART,CBOE,BOX",
        exchange="SMART",
        time_zone_id="US/Eastern",
        liquid_hours="20260825:0930-20260825:1615",
        min_tick=0.01,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _preview(**overrides):
    values = dict(
        ready=True,
        preview_received=True,
        con_id=preflight.CON_ID,
        local_symbol=preflight.LOCAL_SYMBOL,
        expiry=preflight.EXPIRY,
        strike=preflight.STRIKE,
        right=preflight.RIGHT,
        multiplier=preflight.MULTIPLIER,
        margin_change=56182.79,
        errors=(),
        real_order_sent=False,
        live_order_sent=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _settings(*, live=False):
    return SimpleNamespace(
        enable_ibkr_paper=True,
        enable_live_trading=live,
        live_trading_unlocked=live,
    )


def _install(monkeypatch, candidate=None, preview=None):
    selected = candidate or _candidate()
    monkeypatch.setattr(preflight, "SETTINGS", _settings())
    monkeypatch.setattr(
        preflight,
        "_verified_target",
        lambda: (4002, selected, ()),
    )
    monkeypatch.setattr(
        preflight,
        "run_option_whatif_for_candidate",
        lambda port, candidate, **kwargs: preview or _preview(),
    )


def test_permission_preflight_requires_every_broker_spec(monkeypatch):
    _install(monkeypatch)
    result = preflight.run_option_permission_preflight()
    assert result.ready is True
    assert result.market_order_supported is True
    assert result.smart_route_supported is True
    assert result.liquid_hours_metadata_ready is True
    assert result.min_tick == 0.01
    assert result.whatif_ready is True
    assert result.whatif_preview_received is True
    assert result.whatif_local_symbol == preflight.LOCAL_SYMBOL
    assert result.whatif_con_id == preflight.CON_ID
    assert result.real_order_sent is False
    assert result.live_order_sent is False


def test_preflight_passes_same_pinned_candidate_to_whatif(monkeypatch):
    candidate = _candidate()
    seen = {}
    monkeypatch.setattr(preflight, "SETTINGS", _settings())
    monkeypatch.setattr(preflight, "_verified_target", lambda: (4002, candidate, ()))

    def _capture(port, selected, **kwargs):
        seen["port"] = port
        seen["candidate"] = selected
        return _preview()

    monkeypatch.setattr(preflight, "run_option_whatif_for_candidate", _capture)
    result = preflight.run_option_permission_preflight()
    assert result.ready is True
    assert seen == {"port": 4002, "candidate": candidate}


def test_missing_mkt_support_fails_closed(monkeypatch):
    _install(monkeypatch, candidate=_candidate(order_types="LMT,STP"))
    result = preflight.run_option_permission_preflight()
    assert result.ready is False
    assert result.market_order_supported is False


def test_missing_liquid_hours_fails_closed(monkeypatch):
    _install(monkeypatch, candidate=_candidate(liquid_hours=None))
    result = preflight.run_option_permission_preflight()
    assert result.ready is False
    assert result.liquid_hours_metadata_ready is False


def test_whatif_contract_drift_fails_closed(monkeypatch):
    _install(monkeypatch, preview=_preview(con_id=preflight.CON_ID + 1))
    result = preflight.run_option_permission_preflight()
    assert result.ready is False
    assert result.whatif_ready is False


def test_live_lock_blocks_before_broker_calls(monkeypatch):
    monkeypatch.setattr(preflight, "SETTINGS", _settings(live=True))
    monkeypatch.setattr(
        preflight,
        "_verified_target",
        lambda: (_ for _ in ()).throw(AssertionError("broker discovery must not run")),
    )
    result = preflight.run_option_permission_preflight()
    assert result.ready is False
    assert result.real_order_sent is False
    assert result.live_order_sent is False
