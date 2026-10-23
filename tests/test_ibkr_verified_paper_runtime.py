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
            "ai_reason_class": "UNKNOWN_ERROR",
        },
        {
            "ticker": "SPY",
            "technical_signal": "HOLD",
            "ai_signal": "HOLD",
            "final_signal": "HOLD",
            "close": None,
            "ai_provider": "",
            "ai_available": False,
            "ai_reason_class": "UNKNOWN_ERROR",
        },
        {
            "ticker": "9432.T",
            "technical_signal": "HOLD",
            "ai_signal": "HOLD",
            "final_signal": "HOLD",
            "close": None,
            "ai_provider": "",
            "ai_available": False,
            "ai_reason_class": "UNKNOWN_ERROR",
        },
    )


def _run_with_single_record(monkeypatch, record: dict) -> module.VerifiedPaperRuntimeResult:
    _approve(monkeypatch)
    monkeypatch.setattr(module, "audit_ibkr_reconciliation_evidence", lambda: _audit())
    monkeypatch.setattr(
        module.paper_trading_runner,
        "run_paper_trading",
        lambda: {
            "records": [record],
            "paper_orders": [],
            "errors": [],
            "execution_errors": [],
        },
    )
    return module.run_verified_paper_runtime_once(settings=_settings())


@pytest.mark.parametrize(
    "ai_reason,ai_available,expected_class",
    [
        (
            "AI評価中にエラーが発生したため、安全側でHOLDとします。"
            "Gemini API通信に失敗しました: HTTP 503 "
            '{"error": {"code": 503, "status": "UNAVAILABLE", '
            '"message": "high demand, GEMINI_API_KEY=should-never-persist"}}',
            False,
            "HTTP_503",
        ),
        (
            "AI評価中にエラーが発生したため、安全側でHOLDとします。"
            "Gemini API通信に失敗しました: HTTP 429 "
            '{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}',
            False,
            "HTTP_429",
        ),
        (
            "AI評価中にエラーが発生したため、安全側でHOLDとします。"
            "Gemini API通信に失敗しました: HTTP 500 "
            '{"error": {"code": 500, "status": "INTERNAL"}}',
            False,
            "HTTP_OTHER",
        ),
        (
            "AI評価中にエラーが発生したため、安全側でHOLDとします。"
            "Gemini API通信に失敗しました: [Errno 11001] getaddrinfo failed",
            False,
            "NETWORK_ERROR",
        ),
        (
            "AI評価結果の形式が不正なため、安全側でHOLDとします。",
            False,
            "INVALID_RESPONSE",
        ),
        (
            "AIが未設定のため、安全側でHOLDとします。",
            False,
            "NOT_CONFIGURED",
        ),
        (
            "AI評価中にエラーが発生したため、安全側でHOLDとします。"
            "Traceback (most recent call last): ValueError: unexpected failure",
            False,
            "UNKNOWN_ERROR",
        ),
        (
            "テクニカル指標から判断してRSIが過熱域にあるため弱含みと判断します。",
            True,
            "OK",
        ),
    ],
)
def test_ai_failure_reason_is_classified_not_copied_verbatim(
    monkeypatch, ai_reason, ai_available, expected_class
):
    # Regression: before this fix, final_decisions discarded AIReason
    # entirely, so only the latest run's overwritten results/latest_signals
    # .xlsx retained AI-failure causes (503 vs 429 vs other) -- making past
    # causes permanently untraceable. A second independent review (Codex/
    # ChatGPT) then flagged that copying the raw AIReason text verbatim into
    # the existing append-only history log would itself become a new leakage
    # vector, since it may embed a provider's full HTTP error body or
    # exception text. The fix classifies into one of a fixed, pre-approved
    # set of labels and persists only that label -- never the raw text.
    record = {
        "Ticker": "AAPL",
        "AIReason": ai_reason,
        "AIProvider": "gemini",
        "AIAvailable": ai_available,
    }

    result = _run_with_single_record(monkeypatch, record)

    decision = result.final_decisions[0]
    assert decision["ai_reason_class"] == expected_class
    assert decision["ai_reason_class"] in {
        module.AI_REASON_CLASS_OK,
        module.AI_REASON_CLASS_NOT_CONFIGURED,
        module.AI_REASON_CLASS_HTTP_429,
        module.AI_REASON_CLASS_HTTP_503,
        module.AI_REASON_CLASS_HTTP_OTHER,
        module.AI_REASON_CLASS_NETWORK_ERROR,
        module.AI_REASON_CLASS_INVALID_RESPONSE,
        module.AI_REASON_CLASS_UNKNOWN_ERROR,
    }
    # No raw reason text, HTTP body, or secret-looking fragment ever reaches
    # the persisted decision -- only the fixed classification label does.
    serialized = json.dumps(decision, ensure_ascii=False)
    assert "GEMINI_API_KEY" not in serialized
    assert "high demand" not in serialized
    assert "getaddrinfo" not in serialized
    assert "RSI" not in serialized
    assert "Traceback" not in serialized


def test_classify_ai_reason_is_a_pure_fixed_value_mapper():
    assert module.classify_ai_reason("", available=True) == "OK"
    assert module.classify_ai_reason("anything at all", available=True) == "OK"
    assert (
        module.classify_ai_reason("AIが未設定のため、安全側でHOLDとします。", available=False)
        == "NOT_CONFIGURED"
    )
    assert module.classify_ai_reason("HTTP 503 oops", available=False) == "HTTP_503"
    assert module.classify_ai_reason("HTTP 429 oops", available=False) == "HTTP_429"
    assert module.classify_ai_reason("HTTP 418 oops", available=False) == "HTTP_OTHER"
    assert (
        module.classify_ai_reason("completely unrecognized text", available=False)
        == "UNKNOWN_ERROR"
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
    trampoline = Path("ibkr_verified_paper_runtime_once.sh").read_text(
        encoding="utf-8"
    )
    body = Path(
        "scripts/ibkr_verified_paper_runtime_once_sanitized.sh"
    ).read_text(encoding="utf-8")
    text = trampoline + "\n" + body
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
