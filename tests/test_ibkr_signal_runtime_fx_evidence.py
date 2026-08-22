from types import SimpleNamespace

import ai_asset_platform.execution.ibkr_signal_runtime as module


def test_capture_account_fx_rate_accepts_composed_broker_evidence(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_fx_rate",
        lambda **kwargs: SimpleNamespace(ready=True, rate=150.25, source="HISTORICAL_MIDPOINT"),
    )
    assert module._capture_account_fx_rate("USD") == 150.25


def test_capture_account_fx_rate_fails_closed_without_evidence(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_fx_rate",
        lambda **kwargs: SimpleNamespace(ready=False, rate=None, source="UNAVAILABLE"),
    )
    assert module._capture_account_fx_rate("USD") is None


def test_capture_account_fx_rate_identity_needs_no_broker_call(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    called = {"value": False}
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_fx_rate",
        lambda **kwargs: called.__setitem__("value", True),
    )
    assert module._capture_account_fx_rate("JPY") == 1.0
    assert called["value"] is False
