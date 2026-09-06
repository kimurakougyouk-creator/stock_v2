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
