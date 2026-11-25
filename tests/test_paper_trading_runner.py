import json
from types import SimpleNamespace

import pytest

import paper_trading_runner


def _settings(**overrides):
    values = dict(
        enable_paper_trading=True,
        enable_ibkr_paper=True,
        enable_live_trading=False,
        live_trading_unlocked=False,
        account_currency="JPY",
        trailing_stop_percent=5.0,
        max_holding_days=30,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_paper_runner_scans_only_verified_pilot_universe_without_legacy_order_branch(monkeypatch):
    calls = []
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings())
    monkeypatch.setattr(paper_trading_runner, "verified_paper_tickers", lambda: ("AAPL", "SPY", "9432.T"))
    monkeypatch.setattr(paper_trading_runner.signal_runner, "_create_configured_ai_provider", lambda: "TEST_AI")
    monkeypatch.setattr(
        paper_trading_runner.signal_runner,
        "run_signal_scan",
        lambda **kwargs: calls.append(kwargs) or {"records": [], "errors": []},
    )
    result = paper_trading_runner.run_paper_trading()
    assert result["records"] == []
    assert result["errors"] == []
    assert result["paper_orders"] == []
    assert result["execution_errors"] == []
    assert calls == [{
        "tickers": ["AAPL", "SPY", "9432.T"],
        "ai_provider": "TEST_AI",
        "allow_orders": False,
        "allow_email": False,
    }]


def test_paper_runner_rejects_disabled_paper(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings(enable_paper_trading=False))
    with pytest.raises(RuntimeError, match="Paper Tradingが無効"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_rejects_disabled_ibkr_paper(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings(enable_ibkr_paper=False))
    with pytest.raises(RuntimeError, match="IBKR Paperが無効"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_rejects_live_unlocked(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings(live_trading_unlocked=True))
    with pytest.raises(RuntimeError, match="Live Trading"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_rejects_live_trading_enabled(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "SETTINGS", _settings(enable_live_trading=True))
    with pytest.raises(RuntimeError, match="Live Tradingが有効"):
        paper_trading_runner.run_paper_trading()


def test_paper_runner_main_prints_normal_health(monkeypatch, capsys):
    monkeypatch.setattr(paper_trading_runner, "run_paper_trading", lambda: {"records": [{} for _ in range(10)], "errors": []})
    paper_trading_runner.main()
    output = capsys.readouterr().out
    assert "診断結果    : NORMAL" in output
    assert "Paper Tradingは正常です。" in output
    assert "シグナル件数: 10" in output
    assert "エラー件数  : 0" in output
    assert "IBKR Pilot Qty: broker-verified per instrument" in output


def test_paper_runner_main_prints_error_health(monkeypatch, capsys):
    monkeypatch.setattr(paper_trading_runner, "run_paper_trading", lambda: {"records": [{} for _ in range(9)], "errors": ["download error"]})
    paper_trading_runner.main()
    output = capsys.readouterr().out
    assert "診断結果    : ERROR" in output
    assert "1件のエラーが発生しました。" in output
    assert "シグナル件数: 9" in output
    assert "エラー件数  : 1" in output


def test_paper_runner_main_prints_classified_label_never_raw_broker_text(monkeypatch, capsys):
    monkeypatch.setattr(
        paper_trading_runner,
        "run_paper_trading",
        lambda: {
            "records": [{} for _ in range(3)],
            "errors": ["IBKR PaperでFilledを確認できなかったため、注文済みとして記録しません。status=NOT_SENT / message=contract rejected / errors=[{'code': 200, 'message': 'No security definition'}]"],
            "execution_errors": [
                {
                    "ticker": "AAPL",
                    "error": (
                        "IBKR PaperでFilledを確認できなかったため、注文済みとして記録しません。"
                        "status=NOT_SENT / message=contract rejected / "
                        "errors=[{'code': 200, 'message': 'No security definition'}]"
                    ),
                }
            ],
        },
    )
    paper_trading_runner.main()
    output = capsys.readouterr().out
    assert "AAPL: BROKER_FILL_UNCONFIRMED" in output
    assert "No security definition" not in output
    assert "contract rejected" not in output
    assert "NOT_SENT" not in output


def test_paper_runner_main_records_label_and_structured_codes_without_printing_raw_text(
    monkeypatch, capsys, tmp_path
):
    diagnostics_path = tmp_path / "paper_execution_raw_diagnostics.jsonl"
    monkeypatch.setattr(paper_trading_runner, "RAW_EXECUTION_DIAGNOSTICS_PATH", diagnostics_path)
    raw_error = (
        "IBKR PaperでFilledを確認できなかったため、注文済みとして記録しません。"
        "status=NOT_SENT / message=contract rejected / "
        "errors=[{'code': 200, 'message': 'No security definition'}]"
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "run_paper_trading",
        lambda: {
            "records": [{} for _ in range(1)],
            "errors": [raw_error],
            # ibkr_error_codes here is exactly what
            # verified_paper_scan.execute_verified_actions_from_scan() would
            # add from the real exception's own attribute -- i.e. already
            # validated, structured data, never parsed from `raw_error`.
            "execution_errors": [{"ticker": "AAPL", "error": raw_error, "ibkr_error_codes": [200]}],
        },
    )
    paper_trading_runner.main()
    output = capsys.readouterr().out
    assert "No security definition" not in output
    assert "contract rejected" not in output

    lines = diagnostics_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["ticker"] == "AAPL"
    assert "recorded_at" in record
    assert record["label"] == "BROKER_FILL_UNCONFIRMED"
    assert record["ibkr_error_codes"] == [200]
    # Nothing beyond the fixed label and numeric error codes is ever
    # persisted -- no raw text, no free-text fields.
    assert set(record) == {"recorded_at", "ticker", "label", "ibkr_error_codes"}
    assert "No security definition" not in json.dumps(record, ensure_ascii=False)
    assert "contract rejected" not in json.dumps(record, ensure_ascii=False)
    assert "status=NOT_SENT" not in json.dumps(record, ensure_ascii=False)


def test_structured_execution_diagnostic_never_persists_account_id_or_token(monkeypatch, tmp_path):
    diagnostics_path = tmp_path / "paper_execution_raw_diagnostics.jsonl"
    monkeypatch.setattr(paper_trading_runner, "RAW_EXECUTION_DIAGNOSTICS_PATH", diagnostics_path)
    # Not real credentials -- random-looking placeholders shaped like an
    # account id and a long opaque token, deliberately avoiding any
    # recognizable third-party key prefix (e.g. "sk_live_") so this test
    # string is not itself flagged by secret scanners. Also includes a
    # broker-provided "status=" field inside free text -- the Codex-flagged
    # P1 attack shape -- to prove it is no longer extracted at all.
    placeholder_account_id = "DU1234567"
    placeholder_token = "PLACEHOLDERTOKENVALUE0123456789NOTREAL"
    fake_secret_error = (
        f"IBKR Paper注文は送信前に停止しました: account {placeholder_account_id} rejected, "
        f"message=broker rejected status={placeholder_account_id} "
        f"session_credential={placeholder_token} invalid"
    )
    paper_trading_runner._record_execution_diagnostic("AAPL", fake_secret_error)

    persisted_text = diagnostics_path.read_text(encoding="utf-8")
    assert placeholder_account_id not in persisted_text
    assert placeholder_token not in persisted_text

    record = json.loads(persisted_text.strip())
    assert record["ticker"] == "AAPL"
    assert set(record) == {"recorded_at", "ticker", "label"}
    assert record["label"] == "EXECUTION_NOT_ATTEMPTED"


def test_structured_execution_diagnostic_extracts_connection_error_codes_safely(monkeypatch, tmp_path):
    diagnostics_path = tmp_path / "paper_execution_raw_diagnostics.jsonl"
    monkeypatch.setattr(paper_trading_runner, "RAW_EXECUTION_DIAGNOSTICS_PATH", diagnostics_path)
    raw_error = (
        "IBKR Paperへ接続できません: "
        "port=4002: connect returned False (ibkr_error_codes=[326]) | "
        "port=7497: connect returned False (ibkr_error_codes=[502])"
    )
    paper_trading_runner._record_execution_diagnostic("AAPL", raw_error)

    record = json.loads(diagnostics_path.read_text(encoding="utf-8").strip())
    assert record["label"] == "UNKNOWN_ERROR(ibkr_error_codes=[326, 502])"
    assert record["ibkr_error_codes"] == [326, 502]
    assert set(record) == {"recorded_at", "ticker", "label", "ibkr_error_codes"}


def test_order_result_raw_error_codes_reads_only_the_structured_code_field():
    # Codex P1/P2 (HEAD 6cd2803): a regex over the errors=[...] *string*
    # rendering could treat a 'code': NNN...-shaped substring inside the
    # broker's own free-text 'message' as a real code (P1), and a ']'
    # inside a quoted message could truncate the match and drop a real,
    # later code (P2). Reading the structured list directly -- never its
    # string form -- makes both impossible: only the dict's actual 'code'
    # key is ever read, and 'message' text is never touched.
    broker_result = SimpleNamespace(
        errors=[
            {
                "code": 201,
                "message": (
                    "Order rejected - account DU1234567 margin exceeded, "
                    "credential PLACEHOLDERTOKENVALUE0123456789NOTREAL, "
                    "fake embedded marker: 'code': 12345678901234567890"
                ),
            },
            {"code": 2104, "message": "Market data farm connection is OK:[farm]"},
            {"code": 202, "message": "duplicate order]"},
        ]
    )
    raw_codes = paper_trading_runner._order_result_raw_error_codes(broker_result)
    assert raw_codes == [201, 2104, 202]


def test_validated_ibkr_error_codes_rejects_implausible_or_wrong_typed_values():
    # Even if something upstream ever produced a non-plausible "code" (huge
    # int, string, float, bool), the validator -- not string parsing -- is
    # the last line of defense before persistence.
    raw_codes = [201, 12345678901234567890, "326", 4.5, True, -1, 100000, 2104]
    assert paper_trading_runner._validated_ibkr_error_codes(raw_codes) == [201, 2104]


def test_structured_execution_diagnostic_extracts_order_result_error_codes_without_message_text(
    monkeypatch, tmp_path
):
    diagnostics_path = tmp_path / "paper_execution_raw_diagnostics.jsonl"
    monkeypatch.setattr(paper_trading_runner, "RAW_EXECUTION_DIAGNOSTICS_PATH", diagnostics_path)
    raw_error = (
        "IBKR PaperでFilledを確認できなかったため、注文済みとして記録しません。"
        "status=NOT_SENT / message=contract rejected / "
        "errors=[{'code': 201, 'message': 'Order rejected - reason: "
        "account DU1234567 margin exceeded, credential PLACEHOLDERTOKENVALUE0123456789NOTREAL'}, "
        "{'code': 202, 'message': 'duplicate order'}]"
    )
    # The structured codes are passed in directly, exactly as
    # verified_paper_scan would carry them from the exception attribute --
    # never parsed out of raw_error's text.
    paper_trading_runner._record_execution_diagnostic("AAPL", raw_error, [201, 202])

    persisted_text = diagnostics_path.read_text(encoding="utf-8")
    assert "DU1234567" not in persisted_text
    assert "PLACEHOLDERTOKENVALUE0123456789NOTREAL" not in persisted_text
    assert "margin exceeded" not in persisted_text
    assert "duplicate order" not in persisted_text
    assert "contract rejected" not in persisted_text

    record = json.loads(persisted_text.strip())
    assert record["ibkr_error_codes"] == [201, 202]
    assert set(record) == {"recorded_at", "ticker", "label", "ibkr_error_codes"}


def test_structured_execution_diagnostic_merges_connection_and_order_result_codes(monkeypatch, tmp_path):
    diagnostics_path = tmp_path / "paper_execution_raw_diagnostics.jsonl"
    monkeypatch.setattr(paper_trading_runner, "RAW_EXECUTION_DIAGNOSTICS_PATH", diagnostics_path)
    raw_error = "port=4002: connect returned False (ibkr_error_codes=[326])"
    paper_trading_runner._record_execution_diagnostic("AAPL", raw_error, [201])

    record = json.loads(diagnostics_path.read_text(encoding="utf-8").strip())
    assert record["ibkr_error_codes"] == [201, 326]


def test_execute_confirmed_order_attaches_validated_codes_from_structured_broker_result(monkeypatch):
    # End-to-end: _execute_confirmed_ibkr_paper_order's own RuntimeError must
    # carry only the broker result's real structured 'code' values -- not
    # anything derived from its 'message' free text -- as an attribute other
    # callers (verified_paper_scan) read without touching the message text.
    _allow_preflight(monkeypatch, fx=1.0)
    broker_result = SimpleNamespace(
        status="NOT_SENT",
        sent=False,
        order_id=None,
        reached_terminal=False,
        timed_out=False,
        last_known_status=None,
        filled_quantity=0.0,
        avg_fill_price=None,
        message="contract rejected",
        errors=[
            {
                "code": 201,
                "message": "rejected, fake embedded marker: 'code': 99999999999999999999",
            }
        ],
    )
    execution = SimpleNamespace(attempted=True, reason="submitted", broker_result=broker_result)
    monkeypatch.setattr(
        paper_trading_runner, "execute_approved_signal_via_ibkr_paper", lambda **kwargs: execution
    )
    with pytest.raises(RuntimeError) as excinfo:
        paper_trading_runner._execute_confirmed_ibkr_paper_order("9432.T", "BUY", 100, 150.0)
    assert excinfo.value.ibkr_error_codes == [201]


def test_record_execution_diagnostic_never_raises_on_write_failure(monkeypatch):
    monkeypatch.setattr(
        paper_trading_runner,
        "RAW_EXECUTION_DIAGNOSTICS_PATH",
        SimpleNamespace(parent=SimpleNamespace(mkdir=lambda **_: (_ for _ in ()).throw(OSError("disk full")))),
    )
    paper_trading_runner._record_execution_diagnostic("AAPL", "some raw error")


def test_paper_runner_main_prints_ibkr_error_code_on_connection_failure(monkeypatch, capsys):
    """End-to-end: a simulated Paper connection failure must reach the final
    log line as a diagnosable IBKR error code, never as a bare UNKNOWN_ERROR
    and never with the raw message text or account id leaked.

    Regression for the gap identified in PR #374 after merge-readiness
    review: classify_paper_execution_error previously discarded the error
    code captured by _connect_first_available_paper_broker before main()
    printed it.
    """
    monkeypatch.setattr(
        paper_trading_runner,
        "run_paper_trading",
        lambda: {
            "records": [{} for _ in range(1)],
            "errors": [],
            "execution_errors": [
                {
                    "ticker": "AAPL",
                    "error": (
                        "IBKR Paperへ接続できません: port=4002: connect returned False "
                        "(ibkr_error_codes=[326]) | port=7497: connect returned False "
                        "(ibkr_error_codes=[502])"
                    ),
                }
            ],
        },
    )
    paper_trading_runner.main()
    output = capsys.readouterr().out
    assert "AAPL: UNKNOWN_ERROR(ibkr_error_codes=[326, 502])" in output
    assert "connect returned False" not in output
    assert "port=4002" not in output
    assert "port=7497" not in output


def test_unconfirmed_ibkr_result_exposes_observed_details():
    result = SimpleNamespace(status="NOT_SENT", sent=False, order_id=None, reached_terminal=False, timed_out=False, last_known_status=None, filled_quantity=0.0, avg_fill_price=None, message="contract rejected", errors=[{"code": 200, "message": "No security definition"}])
    execution = SimpleNamespace(attempted=True, reason="submitted", broker_result=result)
    message = paper_trading_runner._describe_unconfirmed_ibkr_result(execution)
    assert "status=NOT_SENT" in message
    assert "sent=False" in message
    assert "message=contract rejected" in message
    assert "No security definition" in message


def test_unconfirmed_ibkr_result_exposes_pre_send_stop_reason():
    execution = SimpleNamespace(attempted=False, reason="risk blocked", broker_result=None)
    assert paper_trading_runner._describe_unconfirmed_ibkr_result(execution) == "IBKR Paper注文は送信前に停止しました: risk blocked"


def _filled_execution(quantity: float, price: float = 150.0):
    broker_result = SimpleNamespace(
        sent=True,
        reached_terminal=True,
        last_known_status="Filled",
        filled_quantity=quantity,
        avg_fill_price=price,
    )
    return SimpleNamespace(attempted=True, reason="submitted", broker_result=broker_result)


def _allow_preflight(monkeypatch, *, fx=1.0):
    monkeypatch.setattr(paper_trading_runner, "_preflight_fx_rate", lambda **kwargs: fx)
    monkeypatch.setattr(
        paper_trading_runner,
        "evaluate_verified_paper_preflight",
        lambda **kwargs: SimpleNamespace(allowed=True, reason="passed"),
    )


def test_integrated_paper_pilot_uses_verified_9432_lot(monkeypatch):
    calls = []
    _allow_preflight(monkeypatch, fx=1.0)
    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", lambda **kwargs: calls.append(kwargs) or _filled_execution(100.0))
    monkeypatch.setattr(paper_trading_runner, "_sync_confirmed_fill_to_reporting", lambda: True)
    result = paper_trading_runner._execute_confirmed_ibkr_paper_order("9432.T", "BUY", 100, 150.0)
    assert calls[0]["shares"] == 100
    assert result["shares"] == 100
    assert result["paper_pilot_shares"] == 100


def test_integrated_paper_pilot_uses_verified_aapl_one_share(monkeypatch):
    calls = []
    _allow_preflight(monkeypatch, fx=150.0)
    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", lambda **kwargs: calls.append(kwargs) or _filled_execution(1.0, 300.0))
    monkeypatch.setattr(paper_trading_runner, "_sync_confirmed_fill_to_reporting", lambda: True)
    result = paper_trading_runner._execute_confirmed_ibkr_paper_order("AAPL", "BUY", 100, 300.0)
    assert calls[0]["shares"] == 1
    assert result["strategy_requested_shares"] == 100
    assert result["paper_pilot_shares"] == 1
    assert result["preflight_fx_to_account_rate"] == 150.0


def test_integrated_paper_pilot_uses_verified_spy_one_share(monkeypatch):
    calls = []
    _allow_preflight(monkeypatch, fx=150.0)
    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", lambda **kwargs: calls.append(kwargs) or _filled_execution(1.0, 700.0))
    monkeypatch.setattr(paper_trading_runner, "_sync_confirmed_fill_to_reporting", lambda: True)
    result = paper_trading_runner._execute_confirmed_ibkr_paper_order("SPY", "BUY", 100, 700.0)
    assert calls[0]["shares"] == 1
    assert result["paper_pilot_shares"] == 1


def test_preflight_block_stops_before_broker_runtime(monkeypatch):
    _allow_preflight(monkeypatch, fx=150.0)
    monkeypatch.setattr(
        paper_trading_runner,
        "evaluate_verified_paper_preflight",
        lambda **kwargs: SimpleNamespace(allowed=False, reason="allocation limit"),
    )
    monkeypatch.setattr(
        paper_trading_runner,
        "execute_approved_signal_via_ibkr_paper",
        lambda **kwargs: pytest.fail("must not reach broker runtime"),
    )
    with pytest.raises(RuntimeError, match="allocation limit"):
        paper_trading_runner._execute_confirmed_ibkr_paper_order("SPY", "BUY", 1, 700.0)


def test_integrated_paper_pilot_blocks_unverified_symbol(monkeypatch):
    monkeypatch.setattr(paper_trading_runner, "execute_approved_signal_via_ibkr_paper", lambda **kwargs: pytest.fail("must not reach broker runtime"))
    with pytest.raises(RuntimeError, match="not registered"):
        paper_trading_runner._execute_confirmed_ibkr_paper_order("MSFT", "BUY", 100, 500.0)


def test_integrated_paper_pilot_rejects_non_positive_requested_quantity():
    with pytest.raises(RuntimeError, match="1以上"):
        paper_trading_runner._execute_confirmed_ibkr_paper_order("9432.T", "BUY", 0, 150.0)


def test_integrated_paper_pilot_forwards_strategy_identity(monkeypatch):
    calls = []
    _allow_preflight(monkeypatch, fx=150.0)
    monkeypatch.setattr(
        paper_trading_runner,
        "execute_approved_signal_via_ibkr_paper",
        lambda **kwargs: calls.append(kwargs) or _filled_execution(1.0, 700.0),
    )
    monkeypatch.setattr(
        paper_trading_runner, "_sync_confirmed_fill_to_reporting", lambda: True
    )
    source_sha = "a" * 40
    parameters_sha = "b" * 64

    paper_trading_runner._execute_confirmed_ibkr_paper_order(
        "SPY", "BUY", 1, 700.0, source_sha, parameters_sha
    )

    assert calls[0]["process_start_source_sha"] == source_sha
    assert calls[0]["strategy_parameters_sha"] == parameters_sha
