from pathlib import Path
import json
from types import SimpleNamespace

import pytest

import ai_asset_platform.execution.ibkr_verified_paper_runtime as module


def _settings(**overrides):
    values = dict(
        enable_paper_trading=True,
        enable_ibkr_paper=True,
        enable_live_trading=False,
        live_trading_unlocked=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _audit(**overrides):
    values = dict(
        account_ready=True,
        execution_snapshot_ready=True,
        order_sent=False,
        blockers=(),
        next_action="RECONCILIATION_EVIDENCE_IS_CLEAN",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _approve(monkeypatch):
    monkeypatch.setenv(module.CONFIRMATION_ENV, module.CONFIRMATION_VALUE)


def test_missing_exact_confirmation_blocks_before_audit(monkeypatch):
    monkeypatch.delenv(module.CONFIRMATION_ENV, raising=False)
    monkeypatch.setattr(
        module,
        "audit_ibkr_reconciliation_evidence",
        lambda: pytest.fail("audit must not run without exact confirmation"),
    )
    with pytest.raises(module.VerifiedPaperRuntimeError, match="confirmation"):
        module.run_verified_paper_runtime_once(settings=_settings())


def test_live_unlock_blocks_before_audit(monkeypatch):
    _approve(monkeypatch)
    monkeypatch.setattr(
        module,
        "audit_ibkr_reconciliation_evidence",
        lambda: pytest.fail("audit must not run with Live unlocked"),
    )
    with pytest.raises(module.VerifiedPaperRuntimeError, match="Live Trading"):
        module.run_verified_paper_runtime_once(
            settings=_settings(live_trading_unlocked=True)
        )


def test_unclean_reconciliation_blocks_before_signal_scan(monkeypatch):
    _approve(monkeypatch)
    monkeypatch.setattr(
        module,
        "audit_ibkr_reconciliation_evidence",
        lambda: _audit(
            blockers=(object(),), next_action="LEGACY_EVIDENCE_REMAINS_UNRECOVERABLE"
        ),
    )
    monkeypatch.setattr(
        module.paper_trading_runner,
        "run_paper_trading",
        lambda: pytest.fail("signal scan must not run while reconciliation is dirty"),
    )
    with pytest.raises(module.VerifiedPaperRuntimeError, match="not clean"):
        module.run_verified_paper_runtime_once(settings=_settings())


def test_clean_reconciliation_runs_one_verified_scan(monkeypatch):
    _approve(monkeypatch)
    calls = []
    monkeypatch.setattr(module, "audit_ibkr_reconciliation_evidence", lambda: _audit())
    monkeypatch.setattr(
        module.paper_trading_runner,
        "run_paper_trading",
        lambda: calls.append(1) or {
            "records": [{"Ticker": "AAPL"}, {"Ticker": "SPY"}, {"Ticker": "9432.T"}],
            "paper_orders": [],
            "errors": [],
            "execution_errors": [],
        },
    )

    result = module.run_verified_paper_runtime_once(settings=_settings())

    assert calls == [1]
    assert result.ran is True
    assert result.analysis_record_count == 3
    assert result.confirmed_paper_fill_count == 0
    assert result.error_count == 0
    assert result.final_decisions == (
        {
            "ticker": "AAPL",
            "technical_signal": "HOLD",
            "ai_signal": "HOLD",
            "final_signal": "HOLD",
            "close": None,
            "ai_provider": "",
            "ai_available": False,
        },
        {
            "ticker": "SPY",
            "technical_signal": "HOLD",
            "ai_signal": "HOLD",
            "final_signal": "HOLD",
            "close": None,
            "ai_provider": "",
            "ai_available": False,
        },
        {
            "ticker": "9432.T",
            "technical_signal": "HOLD",
            "ai_signal": "HOLD",
            "final_signal": "HOLD",
            "close": None,
            "ai_provider": "",
            "ai_available": False,
        },
    )


def test_fail_closed_execution_error_is_reported(monkeypatch):
    _approve(monkeypatch)
    monkeypatch.setattr(module, "audit_ibkr_reconciliation_evidence", lambda: _audit())
    error = {"ticker": "SPY", "error": "broker position mismatch"}
    monkeypatch.setattr(
        module.paper_trading_runner,
        "run_paper_trading",
        lambda: {
            "records": [{"Ticker": "SPY"}],
            "paper_orders": [],
            "errors": [error],
            "execution_errors": [error],
        },
    )

    result = module.run_verified_paper_runtime_once(settings=_settings())

    assert result.confirmed_paper_fill_count == 0
    assert result.error_count == 1
    assert result.execution_error_count == 1


def test_wrapper_is_explicit_bounded_paper_only_entrypoint():
    text = Path("ibkr_verified_paper_runtime_once.sh").read_text(encoding="utf-8")
    assert "AI_ASSET_ENABLE_IBKR_PAPER=1" in text
    assert "AI_ASSET_VERIFIED_PAPER_RUNTIME_CONFIRM=RUN_VERIFIED_PAPER_ONLY" in text
    assert "ibkr_verified_paper_runtime" in text
    assert "while true" not in text
    assert "AI_ASSET_ENABLE_LIVE_TRADING" not in text
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED" not in text
    assert "python -m paper_trading_runner" not in text


def test_runtime_record_is_atomically_persisted_and_appended(tmp_path):
    result = module.VerifiedPaperRuntimeResult(
        ran=True,
        reason="verified Paper scan completed",
        analysis_record_count=3,
        confirmed_paper_fill_count=0,
        error_count=0,
        execution_error_count=0,
        started_at="2026-08-26T17:00:00+09:00",
        completed_at="2026-08-26T17:00:02+09:00",
        final_decisions=(
            {
                "ticker": "SPY",
                "technical_signal": "HOLD",
                "ai_signal": "HOLD",
                "final_signal": "HOLD",
                "close": 766.0,
                "ai_provider": "openai",
                "ai_available": True,
            },
        ),
    )
    latest = tmp_path / "latest.json"
    history = tmp_path / "history.jsonl"

    record = module.runtime_result_record(result)
    module.persist_runtime_record(record, latest_path=latest, history_path=history)

    assert json.loads(latest.read_text(encoding="utf-8"))["status"] == "SUCCESS"
    rows = history.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["live_order_sent"] is False
    assert not latest.with_suffix(".json.tmp").exists()


def test_blocked_runtime_record_never_claims_an_order():
    record = module.runtime_failure_record(
        status="BLOCKED",
        reason="reconciliation is not clean",
        started_at="2026-08-26T17:00:00+09:00",
        completed_at="2026-08-26T17:00:01+09:00",
    )
    assert record["status"] == "BLOCKED"
    assert record["confirmed_paper_fill_count"] == 0
    assert record["live_order_sent"] is False
