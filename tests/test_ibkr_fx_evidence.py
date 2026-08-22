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


def test_primary_fx_evidence_wins_without_historical_call(monkeypatch):
    called = {"historical": 0}
    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", lambda **kwargs: _snapshot(ready=True, rate=150.0))
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_historical_fx_rate",
        lambda **kwargs: called.__setitem__("historical", 1),
    )
    result = module.resolve_ibkr_paper_fx_evidence(base_currency="USD", quote_currency="JPY")
    assert result.ready is True
    assert result.rate == 150.0
    assert called["historical"] == 0


def test_historical_midpoint_is_used_when_primary_sources_fail(monkeypatch):
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_fx_rate",
        lambda **kwargs: _snapshot(ready=False, errors=("10197",)),
    )
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_historical_fx_rate",
        lambda **kwargs: _historical(ready=True, rate=150.2, errors=("2106",)),
    )
    result = module.resolve_ibkr_paper_fx_evidence(base_currency="USD", quote_currency="JPY")
    assert result.ready is True
    assert result.rate == 150.2
    assert result.source == "HISTORICAL_MIDPOINT"
    assert result.order_sent is False
    assert "10197" in result.errors


def test_all_sources_missing_remains_fail_closed(monkeypatch):
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_fx_rate",
        lambda **kwargs: _snapshot(ready=False, errors=("10197",)),
    )
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_historical_fx_rate",
        lambda **kwargs: _historical(ready=False, errors=("historical unavailable",)),
    )
    result = module.resolve_ibkr_paper_fx_evidence(base_currency="USD", quote_currency="JPY")
    assert result.ready is False
    assert result.rate is None
    assert result.source == "UNAVAILABLE"
    assert result.order_sent is False
