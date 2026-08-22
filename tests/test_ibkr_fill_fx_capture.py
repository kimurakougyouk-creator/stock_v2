import json
from types import SimpleNamespace

import ai_asset_platform.execution.ibkr_signal_runtime as runtime
from ai_asset_platform.execution.legacy_fill_sync import record_confirmed_fill


def test_same_currency_fx_is_exactly_one_without_broker_call(monkeypatch):
    monkeypatch.setattr(runtime, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    monkeypatch.setattr(
        runtime,
        "preview_ibkr_paper_fx_rate",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not call broker")),
    )
    assert runtime._capture_account_fx_rate("JPY") == 1.0


def test_cross_currency_fx_uses_ready_broker_snapshot(monkeypatch):
    monkeypatch.setattr(runtime, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    seen = {}

    def fake_preview(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(ready=True, rate=150.25)

    monkeypatch.setattr(runtime, "preview_ibkr_paper_fx_rate", fake_preview)
    assert runtime._capture_account_fx_rate("USD") == 150.25
    assert seen == {"base_currency": "USD", "quote_currency": "JPY"}


def test_cross_currency_fx_failure_returns_none(monkeypatch):
    monkeypatch.setattr(runtime, "SETTINGS", SimpleNamespace(account_currency="JPY"))
    monkeypatch.setattr(
        runtime,
        "preview_ibkr_paper_fx_rate",
        lambda **kwargs: SimpleNamespace(ready=False, rate=None),
    )
    assert runtime._capture_account_fx_rate("USD") is None


def test_confirmed_fill_persists_explicit_fx_rate(tmp_path):
    path = tmp_path / "paper_orders.jsonl"
    record = record_confirmed_fill(
        ticker="SPY",
        side="BUY",
        filled_quantity=1,
        avg_fill_price=765.0,
        currency="USD",
        fx_to_account_rate=150.25,
        order_intent_id="intent-fx",
        order_log_path=path,
    )
    assert record["fx_to_account_rate"] == 150.25
    saved = json.loads(path.read_text(encoding="utf-8").strip())
    assert saved["fx_to_account_rate"] == 150.25


def test_confirmed_fill_can_be_preserved_when_fx_unavailable(tmp_path):
    path = tmp_path / "paper_orders.jsonl"
    record = record_confirmed_fill(
        ticker="SPY",
        side="BUY",
        filled_quantity=1,
        avg_fill_price=765.0,
        currency="USD",
        fx_to_account_rate=None,
        order_intent_id="intent-no-fx",
        order_log_path=path,
    )
    assert "fx_to_account_rate" not in record
    assert path.exists()
