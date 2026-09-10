from __future__ import annotations

from pathlib import Path

from ai_asset_platform.brokers.ibkr_live_postfill_evidence import (
    IbkrLivePostFillSnapshot,
    LiveCommissionEvidence,
    LiveExecutionEvidence,
    match_live_postfill,
    persist_live_postfill_snapshot,
    preview_ibkr_live_postfill_snapshot,
)


FP = "a" * 64


def _execution(**overrides):
    data = dict(
        exec_id="exec-1",
        order_id=77,
        perm_id=88,
        symbol="AAPL",
        sec_type="STK",
        currency="USD",
        side="BUY",
        quantity=1.0,
        price=250.0,
        time="20260907  09:31:00",
        account_fingerprint=FP,
    )
    data.update(overrides)
    return LiveExecutionEvidence(**data)


def _commission(**overrides):
    data = dict(exec_id="exec-1", commission=0.35, currency="USD", realized_pnl=None)
    data.update(overrides)
    return LiveCommissionEvidence(**data)


def _snapshot(**overrides):
    data = dict(
        attempted=True,
        connected=True,
        endpoint_port=4001,
        account_fingerprint=FP,
        executions=(_execution(),),
        commissions=(_commission(),),
    )
    data.update(overrides)
    return IbkrLivePostFillSnapshot(**data)


def test_missing_exact_readonly_confirmation_blocks_before_connection():
    result = preview_ibkr_live_postfill_snapshot(confirmation="no")
    assert result.attempted is False
    assert result.connected is False
    assert result.order_sent is False
    assert result.live_order_sent is False


def test_exact_execution_and_commission_prove_native_cash_effect():
    result = match_live_postfill(
        _snapshot(),
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is True
    assert result.execution is not None
    assert result.commission is not None
    assert result.native_cash_effect == -250.35
    assert result.filled_quantity == 1.0
    assert result.vwap_price == 250.0
    assert result.commission_total == 0.35
    assert len(result.executions) == 1
    assert len(result.commissions) == 1


def test_split_fill_aggregates_all_exec_ids_and_commissions():
    snapshot = _snapshot(
        executions=(
            _execution(exec_id="exec-1", quantity=0.4, price=250.0),
            _execution(exec_id="exec-2", quantity=0.6, price=251.0),
        ),
        commissions=(
            _commission(exec_id="exec-1", commission=0.15),
            _commission(exec_id="exec-2", commission=0.20),
        ),
    )
    result = match_live_postfill(
        snapshot,
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is True
    assert result.filled_quantity == 1.0
    assert result.vwap_price == 250.6
    assert result.commission_total == 0.35
    assert result.native_cash_effect == -250.95
    assert tuple(row.exec_id for row in result.executions) == ("exec-1", "exec-2")


def test_split_fill_missing_one_commission_fails_closed():
    snapshot = _snapshot(
        executions=(
            _execution(exec_id="exec-1", quantity=0.4),
            _execution(exec_id="exec-2", quantity=0.6),
        ),
        commissions=(_commission(exec_id="exec-1"),),
    )
    result = match_live_postfill(
        snapshot,
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is False
    assert result.native_cash_effect is None
    assert any("exec-2" in item for item in result.blockers)


def test_split_fill_under_or_over_quantity_fails_closed():
    under = _snapshot(
        executions=(
            _execution(exec_id="exec-1", quantity=0.4),
            _execution(exec_id="exec-2", quantity=0.5),
        ),
        commissions=(
            _commission(exec_id="exec-1"),
            _commission(exec_id="exec-2"),
        ),
    )
    assert match_live_postfill(
        under,
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    ).ready is False

    over = _snapshot(
        executions=(
            _execution(exec_id="exec-1", quantity=0.4),
            _execution(exec_id="exec-2", quantity=0.7),
        ),
        commissions=(
            _commission(exec_id="exec-1"),
            _commission(exec_id="exec-2"),
        ),
    )
    assert match_live_postfill(
        over,
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    ).ready is False


def test_duplicate_execution_or_commission_evidence_fails_closed():
    duplicate_exec = _snapshot(
        executions=(
            _execution(exec_id="exec-1", quantity=0.5),
            _execution(exec_id="exec-1", quantity=0.5),
        ),
        commissions=(_commission(exec_id="exec-1"),),
    )
    result = match_live_postfill(
        duplicate_exec,
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is False
    assert any("duplicate exec_id" in item for item in result.blockers)

    duplicate_commission = _snapshot(
        commissions=(_commission(), _commission(commission=0.36)),
    )
    result = match_live_postfill(
        duplicate_commission,
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is False
    assert any("found 2" in item for item in result.blockers)


def test_wrong_order_identity_fails_closed():
    result = match_live_postfill(
        _snapshot(),
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=999,
        perm_id=88,
    )
    assert result.ready is False
    assert result.execution is None


def test_missing_commission_fails_closed():
    result = match_live_postfill(
        _snapshot(commissions=()),
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is False
    assert result.execution is not None
    assert result.commission is None


def test_wrong_account_fingerprint_fails_closed():
    result = match_live_postfill(
        _snapshot(),
        expected_account_fingerprint="b" * 64,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is False


def test_commission_currency_mismatch_fails_closed():
    result = match_live_postfill(
        _snapshot(commissions=(_commission(currency="JPY"),)),
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is False
    assert result.native_cash_effect is None


def test_persisted_report_has_no_raw_account_id(tmp_path: Path):
    path = tmp_path / "postfill.json"
    persist_live_postfill_snapshot(_snapshot(), report_path=path)
    text = path.read_text(encoding="utf-8")
    assert '"raw_account_id_persisted": false' in text
    assert "DU123" not in text
    assert '"order_sent": false' in text
    assert '"live_order_sent": false' in text


def test_conflicting_exec_id_outside_matched_order_fails_closed():
    conflicting = _snapshot(
        executions=(
            _execution(exec_id="exec-1", order_id=77),
            _execution(exec_id="exec-1", order_id=999),
        ),
    )
    result = match_live_postfill(
        conflicting,
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is False
    assert any("conflicts with Live execution evidence" in item for item in result.blockers)


def test_extreme_price_overflow_fails_closed():
    overflow = _snapshot(executions=(_execution(price=1e308, quantity=2.0),))
    result = match_live_postfill(
        overflow,
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is False
    assert any("overflowed" in item for item in result.blockers)


def test_near_exact_but_not_exact_quantity_now_fails_closed():
    near_exact = _snapshot(executions=(_execution(quantity=1.0000000005),))
    result = match_live_postfill(
        near_exact,
        expected_account_fingerprint=FP,
        ticker="AAPL",
        side="BUY",
        quantity=1,
        order_id=77,
        perm_id=88,
    )
    assert result.ready is False
    assert any("does not equal expected total" in item for item in result.blockers)


def test_module_contains_no_order_transport():
    source = Path(
        "src/ai_asset_platform/brokers/ibkr_live_postfill_evidence.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        ".placeOrder(",
        ".cancelOrder(",
        "enable_live_trading = True",
        "whatIf=True",
    )
    for token in forbidden:
        assert token not in source
