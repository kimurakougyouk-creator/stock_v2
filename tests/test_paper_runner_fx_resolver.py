from types import SimpleNamespace

import paper_trading_runner


def test_preflight_fx_rate_uses_composed_broker_evidence(monkeypatch):
    monkeypatch.setattr(
        paper_trading_runner,
        "SETTINGS",
        SimpleNamespace(account_currency="JPY"),
    )
    calls = []

    def fake_resolver(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(ready=True, rate=150.25, source="HISTORICAL_MIDPOINT")

    monkeypatch.setattr(
        paper_trading_runner,
        "resolve_ibkr_paper_fx_evidence",
        fake_resolver,
    )

    rate = paper_trading_runner._preflight_fx_rate(
        instrument_currency="USD",
        side="BUY",
    )

    assert rate == 150.25
    assert calls == [{"base_currency": "USD", "quote_currency": "JPY"}]


def test_preflight_fx_rate_does_not_need_fx_for_sell(monkeypatch):
    monkeypatch.setattr(
        paper_trading_runner,
        "resolve_ibkr_paper_fx_evidence",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("resolver must not run")),
    )
    assert paper_trading_runner._preflight_fx_rate(
        instrument_currency="USD",
        side="SELL",
    ) is None
