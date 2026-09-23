from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_asset_platform.execution.ibkr_signal_runtime as module


def test_exact_runtime_source_sha_accepts_git_head(monkeypatch):
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=("a" * 40) + "\n"),
    )
    assert module._exact_runtime_source_sha(Path(".")) == "a" * 40


def test_exact_runtime_source_sha_blocks_before_broker_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        module,
        "SETTINGS",
        SimpleNamespace(enable_paper_trading=True, enable_ibkr_paper=True),
    )
    monkeypatch.setattr(
        module,
        "_exact_runtime_source_sha",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no source")),
    )
    monkeypatch.setattr(
        module,
        "_connect_first_available_paper_broker",
        lambda: pytest.fail("broker connection must not happen without source SHA"),
    )

    with pytest.raises(RuntimeError, match="no source"):
        module.execute_approved_signal_via_ibkr_paper(
            ticker="AAPL",
            signal="BUY",
            shares=1,
            order_intent_id="signal-runner:AAPL:BUY:1:bar",
            process_start_source_sha="a" * 40,
            strategy_parameters_sha="b" * 64,
        )


def test_source_drift_blocks_before_broker(monkeypatch):
    monkeypatch.setattr(
        module,
        "SETTINGS",
        SimpleNamespace(enable_paper_trading=True, enable_ibkr_paper=True),
    )
    monkeypatch.setattr(module, "_exact_runtime_source_sha", lambda *args, **kwargs: "b" * 40)
    monkeypatch.setattr(
        module,
        "_connect_first_available_paper_broker",
        lambda: pytest.fail("broker connection must not happen after source drift"),
    )

    with pytest.raises(RuntimeError, match="changed after process start"):
        module.execute_approved_signal_via_ibkr_paper(
            ticker="AAPL",
            signal="BUY",
            shares=1,
            order_intent_id="signal-runner:AAPL:BUY:1:bar",
            process_start_source_sha="a" * 40,
            strategy_parameters_sha="c" * 64,
        )


def test_missing_parameter_identity_blocks_before_broker(monkeypatch):
    monkeypatch.setattr(
        module,
        "SETTINGS",
        SimpleNamespace(enable_paper_trading=True, enable_ibkr_paper=True),
    )
    monkeypatch.setattr(
        module,
        "_connect_first_available_paper_broker",
        lambda: pytest.fail("broker connection must not happen without parameter identity"),
    )

    with pytest.raises(RuntimeError, match="parameter identity"):
        module.execute_approved_signal_via_ibkr_paper(
            ticker="AAPL",
            signal="BUY",
            shares=1,
            order_intent_id="signal-runner:AAPL:BUY:1:bar",
            process_start_source_sha="a" * 40,
            strategy_parameters_sha=None,
        )
