from types import SimpleNamespace

import ai_asset_platform.brokers.ibkr_fx_evidence as module


def _snapshot(*, ready, rate=None, source="MARKET_DATA", errors=()):
    return SimpleNamespace(
        connected=True,
        endpoint_port=4002,
        base_currency="USD",
        quote_currency="JPY",
        exchange="IDEALPRO",
        bid=149.9 if ready else None,
        ask=150.1 if ready else None,
        rate=rate,
        source=source,
        order_sent=False,
        errors=errors,
        ready=ready,
    )


def _historical(*, ready, rate=None, errors=()):
    return SimpleNamespace(
        connected=True,
        endpoint_port=4002,
        base_currency="USD",
        quote_currency="JPY",
        exchange="IDEALPRO",
        rate=rate,
        source="HISTORICAL_MIDPOINT",
        order_sent=False,
        errors=errors,
        ready=ready,
    )


def test_live_market_evidence_wins_without_historical_call(monkeypatch):
    calls = []
    monkeypatch.setattr(
        module,
        "_request_market_snapshot",
        lambda contract, *, market_data_type, timeout: (
            calls.append(market_data_type) or _snapshot(ready=True, rate=150.0)
        ),
    )
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_historical_fx_rate",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("historical must not run")),
    )
    result = module.resolve_ibkr_paper_fx_evidence(base_currency="USD", quote_currency="JPY")
    assert result.ready is True
    assert result.rate == 150.0
    assert calls == [1]


def test_historical_midpoint_runs_after_all_market_modes_fail(monkeypatch):
    calls = []

    def missing_market(contract, *, market_data_type, timeout):
        calls.append(market_data_type)
        return _snapshot(ready=False, source=f"TYPE_{market_data_type}", errors=(f"market-{market_data_type}",))

    monkeypatch.setattr(module, "_request_market_snapshot", missing_market)
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_historical_fx_rate",
        lambda **kwargs: _historical(ready=True, rate=150.2, errors=("historical-ok",)),
    )
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_account_fx_rate",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("account fallback must not run")),
    )
    result = module.resolve_ibkr_paper_fx_evidence(base_currency="USD", quote_currency="JPY")
    assert calls == [1, 3, 4]
    assert result.ready is True
    assert result.rate == 150.2
    assert result.source == "HISTORICAL_MIDPOINT"
    assert result.order_sent is False
    assert "market-1" in result.errors


def test_account_updates_is_last_documented_fallback(monkeypatch):
    monkeypatch.setattr(
        module,
        "_request_market_snapshot",
        lambda *args, **kwargs: _snapshot(ready=False, errors=("market unavailable",)),
    )
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_historical_fx_rate",
        lambda **kwargs: _historical(ready=False, errors=("historical unavailable",)),
    )
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_account_fx_rate",
        lambda **kwargs: _snapshot(ready=True, rate=150.4, source="ACCOUNT_EXCHANGE_RATE"),
    )
    result = module.resolve_ibkr_paper_fx_evidence(base_currency="USD", quote_currency="JPY")
    assert result.ready is True
    assert result.rate == 150.4
    assert result.source == "ACCOUNT_EXCHANGE_RATE"


def test_all_sources_missing_remains_fail_closed(monkeypatch):
    monkeypatch.setattr(
        module,
        "_request_market_snapshot",
        lambda *args, **kwargs: _snapshot(ready=False, errors=("market unavailable",)),
    )
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_historical_fx_rate",
        lambda **kwargs: _historical(ready=False, errors=("historical unavailable",)),
    )
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_account_fx_rate",
        lambda **kwargs: _snapshot(ready=False, source="ACCOUNT_EXCHANGE_RATE", errors=("account unavailable",)),
    )
    result = module.resolve_ibkr_paper_fx_evidence(base_currency="USD", quote_currency="JPY")
    assert result.ready is False
    assert result.rate is None
    assert result.source == "UNAVAILABLE"
    assert result.order_sent is False


def test_identity_rate_avoids_all_broker_calls(monkeypatch):
    monkeypatch.setattr(
        module,
        "_request_market_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("broker must not run")),
    )
    result = module.resolve_ibkr_paper_fx_evidence(base_currency="JPY", quote_currency="JPY")
    assert result.ready is True
    assert result.rate == 1.0
    assert result.source == "IDENTITY"
