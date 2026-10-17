from types import SimpleNamespace

import ai_asset_platform.execution.ibkr_signal_runtime as module
from ai_asset_platform.brokers.ibkr_fx_historical import (
    preview_ibkr_paper_historical_fx_rate,
)


def test_fx_capture_uses_the_reproducible_historical_source():
    # Regression for Codex P1 finding on PR #350: a live/delayed market quote
    # can never be fetched again after the fact, so later independent
    # broker-provenance verification (strategy_broker_provenance.py) could
    # never reproduce a captured rate that came from a live/delayed snapshot.
    # ibkr_execution_reconcile.py's own FX resolution already uses this same
    # historical-only source for exactly this reproducibility reason; this
    # capture point must match it.
    assert module.preview_ibkr_paper_fx_rate is preview_ibkr_paper_historical_fx_rate


EXEC_TIME = "20261016 09:00:00 Asia/Tokyo"


def test_capture_account_fx_rate_accepts_composed_broker_evidence(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    observed = {}

    def _fetch(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(ready=True, rate=150.25, source="HISTORICAL_MIDPOINT")

    monkeypatch.setattr(module, "preview_ibkr_paper_fx_rate", _fetch)
    assert module._capture_account_fx_rate("USD", execution_time=EXEC_TIME) == 150.25
    # Regression for Codex P1 finding on PR #350: the capture must anchor to
    # the broker's own execution time, not an unanchored "now" query, so a
    # later independent re-query anchored to the same exec_id can select the
    # identical historical bar instead of a neighboring one.
    assert observed["end_datetime"] == EXEC_TIME
    assert observed["reference_timestamp"] is not None


def test_capture_account_fx_rate_fails_closed_without_evidence(monkeypatch):
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_fx_rate",
        lambda **kwargs: SimpleNamespace(ready=False, rate=None, source="UNAVAILABLE"),
    )
    assert module._capture_account_fx_rate("USD", execution_time=EXEC_TIME) is None


def test_capture_account_fx_rate_fails_closed_without_execution_time(monkeypatch):
    # Regression for Codex P1 finding on PR #350: an unanchored FX capture
    # reintroduces the exact bucket-mismatch bug this fix exists to close,
    # so a missing/unparseable execution_time must fail closed without even
    # attempting a broker call.
    monkeypatch.setattr(module, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    called = {"value": False}
    monkeypatch.setattr(
        module,
        "preview_ibkr_paper_fx_rate",
        lambda **kwargs: called.__setitem__("value", True),
    )
    assert module._capture_account_fx_rate("USD") is None
    assert module._capture_account_fx_rate("USD", execution_time="not a time") is None
    assert called["value"] is False


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
