from types import SimpleNamespace

import pytest

import ai_asset_platform.brokers.ibkr_multiasset_readonly_audit as module


def _result(**kwargs):
    defaults = dict(
        connected=True,
        endpoint_port=4002,
        candidates=(object(),),
        order_sent=False,
        errors=(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults, resolved=bool(defaults["connected"] and defaults["candidates"] and not defaults["order_sent"]))


def test_batch_audit_never_requires_future_target(monkeypatch):
    stock_calls = []
    fx_calls = []
    future_calls = []

    monkeypatch.setattr(module, "discover_ibkr_paper_global_stock", lambda **kwargs: stock_calls.append(kwargs) or _result(symbol=kwargs["symbol"], exchange=kwargs["exchange"], currency=kwargs["currency"]))
    monkeypatch.setattr(module, "discover_ibkr_paper_fx", lambda **kwargs: fx_calls.append(kwargs) or _result(base_currency=kwargs["base_currency"], quote_currency=kwargs["quote_currency"], exchange=kwargs["exchange"]))
    monkeypatch.setattr(module, "discover_ibkr_paper_futures", lambda **kwargs: future_calls.append(kwargs) or _result(symbol=kwargs["symbol"], exchange=kwargs["exchange"], currency=kwargs["currency"]))

    result = module.run_multiasset_readonly_audit(timeout=1.0)

    assert result.core_resolved is True
    assert result.order_sent is False
    assert result.future is None
    assert future_calls == []
    assert stock_calls[0]["symbol"] == "9432"
    assert stock_calls[0]["exchange"] == "TSEJ"
    assert fx_calls[0]["base_currency"] == "USD"
    assert fx_calls[0]["quote_currency"] == "JPY"


def test_future_discovery_is_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(module, "discover_ibkr_paper_global_stock", lambda **kwargs: _result(symbol=kwargs["symbol"], exchange=kwargs["exchange"], currency=kwargs["currency"]))
    monkeypatch.setattr(module, "discover_ibkr_paper_fx", lambda **kwargs: _result(base_currency=kwargs["base_currency"], quote_currency=kwargs["quote_currency"], exchange=kwargs["exchange"]))
    seen = []
    monkeypatch.setattr(module, "discover_ibkr_paper_futures", lambda **kwargs: seen.append(kwargs) or _result(symbol=kwargs["symbol"], exchange=kwargs["exchange"], currency=kwargs["currency"]))

    result = module.run_multiasset_readonly_audit(
        future_symbol="TEST",
        future_exchange="TESTEX",
        future_currency="USD",
        timeout=1.0,
    )

    assert result.future is not None
    assert result.future.resolved is True
    assert seen == [{"symbol": "TEST", "exchange": "TESTEX", "currency": "USD", "timeout": 1.0}]
    assert result.order_sent is False


def test_partial_future_target_fails_closed(monkeypatch):
    monkeypatch.setattr(module, "discover_ibkr_paper_global_stock", lambda **kwargs: _result(symbol=kwargs["symbol"], exchange=kwargs["exchange"], currency=kwargs["currency"]))
    monkeypatch.setattr(module, "discover_ibkr_paper_fx", lambda **kwargs: _result(base_currency=kwargs["base_currency"], quote_currency=kwargs["quote_currency"], exchange=kwargs["exchange"]))

    with pytest.raises(ValueError, match="provided together"):
        module.run_multiasset_readonly_audit(future_symbol="TEST")


def test_core_resolved_fails_when_any_discovery_sent_order(monkeypatch):
    monkeypatch.setattr(module, "discover_ibkr_paper_global_stock", lambda **kwargs: _result(symbol=kwargs["symbol"], exchange=kwargs["exchange"], currency=kwargs["currency"], order_sent=True))
    monkeypatch.setattr(module, "discover_ibkr_paper_fx", lambda **kwargs: _result(base_currency=kwargs["base_currency"], quote_currency=kwargs["quote_currency"], exchange=kwargs["exchange"]))

    result = module.run_multiasset_readonly_audit()

    assert result.order_sent is True
    assert result.core_resolved is False
